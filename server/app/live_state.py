"""
Einfacher In-Memory-Speicher für den aktuellen Live-Zustand aller Sensoren.

Da FastAPI in einem einzigen Prozess läuft und Python's GIL einfache
dict-Zugriffe atomar hält, ist dieser Ansatz für unsere Nutzlast sicher.
"""

import time
from typing import Optional

# sensor_id → angereichertes Zustandsdict + interner Zeitstempel
_state: dict = {}


def build_response(offline_timeout_s: float = 15.0) -> dict:
    """Baut das Standard-Live-Response-Dict auf (für REST und WebSocket)."""
    sensors_out: dict = {}
    for sensor_id, data in get_all().items():
        elapsed = seconds_since(sensor_id)
        online  = elapsed is not None and elapsed < offline_timeout_s
        public  = {k: v for k, v in data.items() if not k.startswith("_")}
        sensors_out[sensor_id] = {
            **public,
            "online":                online,
            "last_seen_seconds_ago": round(elapsed, 2) if elapsed is not None else None,
        }
    return {
        "timestamp_ms": int(time.time() * 1000),
        "sensor_count": len(sensors_out),
        "sensors":      sensors_out,
    }


def update(sensor_id: str, data: dict) -> None:
    """Speichert neuen Sensorzustand mit aktuellem Zeitstempel."""
    _state[sensor_id] = {**data, "_last_seen_mono": time.monotonic()}


def get(sensor_id: str) -> Optional[dict]:
    return _state.get(sensor_id)


def get_all() -> dict:
    return dict(_state)


def seconds_since(sensor_id: str) -> Optional[float]:
    """Gibt zurück, wie viele Sekunden seit dem letzten Update vergangen sind."""
    entry = _state.get(sensor_id)
    if entry is None:
        return None
    return time.monotonic() - entry["_last_seen_mono"]


def clear() -> None:
    """Leert den State – nur für Tests."""
    _state.clear()
