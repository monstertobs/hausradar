"""
POST /api/simulate/motion  – nimmt simulierte (oder echte) Sensordaten entgegen
GET  /api/live             – gibt den aktuellen Live-Zustand aller Sensoren zurück
"""

import logging
from typing import Annotated, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator

from app.coordinate_transform import full_transform
from app import database as db
from app import live_state
from app.websocket_service import manager as ws_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Datenmodelle (Pydantic)
# ---------------------------------------------------------------------------

class Target(BaseModel):
    id: int
    x_mm: float
    y_mm: float
    speed_mm_s: float = 0.0
    distance_mm: float = 0.0
    angle_deg: Optional[float] = None

    @field_validator("y_mm")
    @classmethod
    def y_must_be_nonneg(cls, v: float) -> float:
        if v < 0:
            raise ValueError("y_mm muss ≥ 0 sein (Entfernung vom Sensor)")
        return v


class MotionPayload(BaseModel):
    sensor_id: str
    room_id: str
    timestamp_ms: int
    target_count: int
    targets: Annotated[List[Target], Field(max_length=3)]

    @field_validator("timestamp_ms")
    @classmethod
    def ts_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("timestamp_ms muss eine positive Zahl sein")
        return v

    @model_validator(mode="after")
    def check_target_count(self) -> "MotionPayload":
        if self.target_count != len(self.targets):
            raise ValueError(
                f"target_count ({self.target_count}) stimmt nicht mit "
                f"len(targets) ({len(self.targets)}) überein"
            )
        return self


# ---------------------------------------------------------------------------
# POST /api/simulate/motion
# ---------------------------------------------------------------------------

@router.post("/simulate/motion", status_code=200)
async def simulate_motion(payload: MotionPayload, request: Request):
    """Nimmt einen Bewegungsdatensatz entgegen, rechnet Koordinaten um,
    speichert den Zustand und sendet ein WebSocket-Update an alle Clients.
    In Production-Umgebung deaktiviert."""

    env = request.app.state.settings.get("environment", "development")
    if env == "production":
        raise HTTPException(status_code=404, detail="Not found")

    sensors = request.app.state.sensors
    rooms   = request.app.state.rooms

    # Sensor validieren
    sensor = next((s for s in sensors if s["id"] == payload.sensor_id), None)
    if sensor is None:
        known = ", ".join(s["id"] for s in sensors)
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unbekannter Sensor '{payload.sensor_id}'. "
                f"Bekannte Sensoren: {known}"
            ),
        )

    # room_id muss zum Sensor passen
    if sensor["room_id"] != payload.room_id:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Sensor '{payload.sensor_id}' gehört zu Raum "
                f"'{sensor['room_id']}', nicht zu '{payload.room_id}'"
            ),
        )

    # Raum laden
    room = next((r for r in rooms if r["id"] == payload.room_id), None)
    if room is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unbekannter Raum '{payload.room_id}'",
        )

    # Targets transformieren
    enriched: list = []
    for t in payload.targets:
        tf = full_transform(sensor, room, {"x_mm": t.x_mm, "y_mm": t.y_mm})
        enriched.append({
            "id":          t.id,
            "x_mm":        t.x_mm,
            "y_mm":        t.y_mm,
            "room_x_mm":   round(tf["room_x_mm"],  1),
            "room_y_mm":   round(tf["room_y_mm"],  1),
            "floorplan_x": round(tf["floorplan_x"], 3),
            "floorplan_y": round(tf["floorplan_y"], 3),
            "inside_room": tf["inside_room"],
            "zone_id":     tf["zone_id"],
            "speed_mm_s":  t.speed_mm_s,
            "distance_mm": t.distance_mm,
            "angle_deg":   t.angle_deg,
        })

    live_state.update(payload.sensor_id, {
        "sensor_id":    payload.sensor_id,
        "room_id":      payload.room_id,
        "timestamp_ms": payload.timestamp_ms,
        "target_count": len(enriched),
        "targets":      enriched,
    })

    try:
        db.record_motion(
            db_path=request.app.state.db_path,
            sensor_id=payload.sensor_id,
            room_id=payload.room_id,
            timestamp_ms=payload.timestamp_ms,
            targets=enriched,
            max_writes_per_second=_max_writes(request),
        )
    except Exception as exc:
        logger.warning("DB-Schreiben fehlgeschlagen: %s", exc)

    # WebSocket-Broadcast an alle verbundenen Browser
    if ws_manager.connection_count > 0:
        timeout = _offline_timeout(request)
        await ws_manager.broadcast(live_state.build_response(timeout))

    logger.debug(
        "simulate/motion: sensor=%s targets=%d ws_clients=%d",
        payload.sensor_id, len(enriched), ws_manager.connection_count,
    )
    return {"ok": True, "targets_processed": len(enriched)}


# ---------------------------------------------------------------------------
# GET /api/live
# ---------------------------------------------------------------------------

@router.get("/live")
def get_live(request: Request):
    """Gibt den aktuellen Live-Zustand aller Sensoren zurück."""
    return live_state.build_response(_offline_timeout(request))


# ---------------------------------------------------------------------------
# Hilfsfunktion
# ---------------------------------------------------------------------------

def _offline_timeout(request: Request) -> float:
    return request.app.state.settings.get("live", {}).get(
        "sensor_offline_timeout_seconds", 10
    )


def _max_writes(request: Request) -> float:
    return request.app.state.settings.get("database", {}).get(
        "max_writes_per_second_per_sensor", 2
    )
