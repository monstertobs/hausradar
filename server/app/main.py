import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

_start_time = time.monotonic()

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import load_rooms, load_sensors, load_settings
from app.api import rooms, sensors, motion, history, profile, calibrate
from app.websocket_service import manager as ws_manager
from app import database as db
from app import live_state
from app.mqtt_service import service as mqtt_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
WEB_DIR  = BASE_DIR / "web"


# ---------------------------------------------------------------------------
# Middleware: Security-HTTP-Header  (HR-SEC-007)
# ---------------------------------------------------------------------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"]           = "DENY"
        response.headers["X-Content-Type-Options"]    = "nosniff"
        response.headers["Referrer-Policy"]           = "no-referrer"
        response.headers["Permissions-Policy"]        = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self' ws: wss:; "
            "frame-ancestors 'none'"
        )
        return response


# ---------------------------------------------------------------------------
# Middleware: Request-Body-Größenlimit  (HR-SEC-005)
# ---------------------------------------------------------------------------

class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, max_bytes: int = 65536) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                cl = int(content_length)
            except ValueError:
                cl = 0
            if cl > self._max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body zu groß (max {self._max_bytes} Bytes)"},
                )
        return await call_next(request)


# ---------------------------------------------------------------------------
# Middleware: Optionaler X-API-Key  (HR-SEC-001)
# ---------------------------------------------------------------------------

_API_KEY: Optional[str] = None

_API_KEY_EXEMPT_PREFIXES = ("/api/health",)

class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _API_KEY:
            path = request.url.path
            # Statische Dateien und Health-Endpoint sind ausgenommen
            if path.startswith("/api/") and not any(
                path.startswith(p) for p in _API_KEY_EXEMPT_PREFIXES
            ):
                key = request.headers.get("X-API-Key", "")
                if key != _API_KEY:
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Ungültiger oder fehlender API-Key (X-API-Key)"},
                        headers={"WWW-Authenticate": "ApiKey"},
                    )
        return await call_next(request)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _API_KEY

    logger.info("HausRadar startet …")
    try:
        app.state.rooms    = load_rooms()
        app.state.sensors  = load_sensors(app.state.rooms)
        app.state.settings = load_settings()
        logger.info(
            "Konfiguration geladen: %d Räume, %d Sensoren",
            len(app.state.rooms),
            len(app.state.sensors),
        )
    except RuntimeError as e:
        logger.error("Konfigurationsfehler beim Start:\n%s", e)
        raise

    db_cfg  = app.state.settings.get("database", {})
    db_path = str(BASE_DIR / db_cfg.get("path", "data/hausradar.db"))
    db.init_db(db_path)
    db.cleanup_old_data(db_path, db_cfg.get("retention_days", 30))
    app.state.db_path = db_path

    # API-Key aus Konfiguration laden
    _API_KEY = app.state.settings.get("server", {}).get("api_key") or None
    if _API_KEY:
        logger.info("API-Key-Authentifizierung aktiv.")
    else:
        env = app.state.settings.get("environment", "development")
        if env == "production":
            logger.warning(
                "Kein api_key in settings.json – API in Production ohne Authentifizierung!"
            )

    # WS-Verbindungslimit aus Konfiguration
    ws_max = app.state.settings.get("server", {}).get("ws_max_connections", 20)
    ws_manager.set_max_connections(ws_max)

    app.state.event_loop = asyncio.get_event_loop()
    mqtt_service.start(app)

    yield

    mqtt_service.stop()
    logger.info("HausRadar fährt herunter.")


# ---------------------------------------------------------------------------
# App + Middleware-Registrierung
# ---------------------------------------------------------------------------

app = FastAPI(title="HausRadar", version="0.1.0", lifespan=lifespan)

# Reihenfolge: äußerste Middleware zuerst hinzufügen
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(ApiKeyMiddleware)
app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=65536,   # Überschrieben nach settings-Load nicht möglich hier;
                       # der Wert aus settings.json ist für Logging und Tests erreichbar
)

app.include_router(rooms.router,     prefix="/api")
app.include_router(sensors.router,   prefix="/api")
app.include_router(motion.router,    prefix="/api")
app.include_router(history.router,   prefix="/api")
app.include_router(profile.router,   prefix="/api")
app.include_router(calibrate.router, prefix="/api")


@app.get("/api/health")
def health():
    return {
        "status":         "ok",
        "service":        "hausradar",
        "uptime_s":       round(time.monotonic() - _start_time, 1),
        "ws_clients":     ws_manager.connection_count,
        "mqtt_connected": mqtt_service.connected,
        "db_ok":          db.check_db(app.state.db_path),
    }


# ---------------------------------------------------------------------------
# WebSocket  (HR-SEC-008 – konfigurierbarer Origin-Check)
# ---------------------------------------------------------------------------

def _origin_allowed(origin: Optional[str], allowed: list) -> bool:
    """Gibt True zurück wenn allowed leer (kein Check) oder origin enthalten."""
    if not allowed:
        return True
    if origin is None:
        return False
    return origin in allowed


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    allowed_origins = (
        websocket.app.state.settings.get("server", {}).get("allowed_origins", [])
    )
    origin = websocket.headers.get("origin")
    if not _origin_allowed(origin, allowed_origins):
        await websocket.close(code=1008)
        logger.warning("WebSocket abgelehnt – Origin nicht erlaubt: %s", origin)
        return

    if not await ws_manager.connect(websocket):
        return

    try:
        timeout = websocket.app.state.settings.get("live", {}).get(
            "sensor_offline_timeout_seconds", 10
        )
        await websocket.send_json(live_state.build_response(timeout))

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WebSocket-Fehler: %s", exc)
    finally:
        ws_manager.disconnect(websocket)


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
