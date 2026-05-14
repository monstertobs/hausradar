"""
API-Endpunkte für Auto-Kalibrierung.

GET  /api/sensors/{id}/auto-calibration          – Vorschlag abrufen
POST /api/sensors/{id}/auto-calibration/apply    – Vorschlag anwenden
POST /api/sensors/{id}/auto-calibration/reset    – Datenpuffer löschen
GET  /api/auto-calibration/status                – Überblick alle Sensoren
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import auto_calibration
from app.config_io import load_json, save_json

logger = logging.getLogger(__name__)
router = APIRouter()

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


# ──────────────────────────────────────────────────────────────────────────────
# Überblick: alle Sensoren
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/auto-calibration/status")
def get_status(request: Request):
    """Zeigt Datenstand und Vorschlag für alle bekannten Sensoren."""
    sensors = request.app.state.sensors
    rooms   = request.app.state.rooms
    room_map = {r["id"]: r for r in rooms}
    counts   = auto_calibration.get_all_counts()

    result = []
    for sensor in sensors:
        sid  = sensor["id"]
        room = room_map.get(sensor.get("room_id", ""))
        n    = counts.get(sid, 0)
        suggestion      = auto_calibration.suggest(sid, room) if room else None
        room_size_sugg  = auto_calibration.suggest_room_size(sid)
        result.append({
            "sensor_id":         sid,
            "sensor_name":       sensor.get("name", sid),
            "room_id":           sensor.get("room_id"),
            "sample_count":      n,
            "min_samples":       auto_calibration.MIN_SAMPLES,
            "ready":             n >= auto_calibration.MIN_SAMPLES,
            "suggestion":        suggestion,
            "room_size_suggestion": room_size_sugg,
        })

    return {"sensors": result}


# ──────────────────────────────────────────────────────────────────────────────
# Einzelner Sensor: Vorschlag
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/sensors/{sensor_id}/auto-calibration")
def get_suggestion(sensor_id: str, request: Request):
    sensors = request.app.state.sensors
    rooms   = request.app.state.rooms

    sensor = next((s for s in sensors if s["id"] == sensor_id), None)
    if sensor is None:
        raise HTTPException(404, f"Sensor '{sensor_id}' nicht gefunden")

    room = next((r for r in rooms if r["id"] == sensor.get("room_id", "")), None)
    if room is None:
        raise HTTPException(400, "Sensor hat keinen gültigen Raum")

    n = auto_calibration.get_sample_count(sensor_id)
    suggestion = auto_calibration.suggest(sensor_id, room)

    if suggestion is None:
        raise HTTPException(
            425,
            f"Noch nicht genug Daten ({n}/{auto_calibration.MIN_SAMPLES} Messungen). "
            "Bitte im Raum bewegen und warten."
        )

    return {
        "sensor_id":      sensor_id,
        "current": {
            "rotation_deg": sensor.get("rotation_deg", 0),
            "x_mm":         sensor.get("x_mm", 0),
            "y_mm":         sensor.get("y_mm", 0),
        },
        **suggestion,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Vorschlag anwenden
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/sensors/{sensor_id}/auto-calibration/apply")
def apply_suggestion(sensor_id: str, request: Request):
    """Schreibt den aktuellen Vorschlag in sensors.json."""
    sensors = request.app.state.sensors
    rooms   = request.app.state.rooms

    sensor = next((s for s in sensors if s["id"] == sensor_id), None)
    if sensor is None:
        raise HTTPException(404, f"Sensor '{sensor_id}' nicht gefunden")

    room = next((r for r in rooms if r["id"] == sensor.get("room_id", "")), None)
    if room is None:
        raise HTTPException(400, "Sensor hat keinen gültigen Raum")

    suggestion = auto_calibration.suggest(sensor_id, room)
    if suggestion is None:
        raise HTTPException(
            425,
            f"Noch nicht genug Daten ({auto_calibration.get_sample_count(sensor_id)}"
            f"/{auto_calibration.MIN_SAMPLES} Messungen)"
        )

    sensors_path = CONFIG_DIR / "sensors.json"
    sensors_data = load_json(sensors_path)

    for s in sensors_data:
        if s["id"] == sensor_id:
            old_rot = s.get("rotation_deg", 0)
            old_x   = s.get("x_mm", 0)
            s["rotation_deg"] = suggestion["rotation_deg"]
            s["x_mm"]         = suggestion["sensor_x_mm"]
            s["y_mm"]         = suggestion["sensor_y_mm"]
            logger.info(
                "Auto-Kalibrierung angewendet: %s rotation %d°→%d°, x_mm %d→%d",
                sensor_id, old_rot, suggestion["rotation_deg"], old_x, suggestion["sensor_x_mm"]
            )
            break

    save_json(sensors_path, sensors_data)

    from app.config import load_sensors
    request.app.state.sensors = load_sensors(request.app.state.rooms)

    return {
        "status":         "ok",
        "sensor_id":      sensor_id,
        "rotation_deg":   suggestion["rotation_deg"],
        "sensor_x_mm":    suggestion["sensor_x_mm"],
        "confidence":     suggestion["confidence"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Raumgröße schätzen (M23)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/sensors/{sensor_id}/auto-calibration/room-size")
def get_room_size_suggestion(sensor_id: str, request: Request):
    """Schätzt Raummaße aus dem Bewegungsprofil (unabhängig von bekannten Raummaßen)."""
    sensors = request.app.state.sensors
    sensor  = next((s for s in sensors if s["id"] == sensor_id), None)
    if sensor is None:
        raise HTTPException(404, f"Sensor '{sensor_id}' nicht gefunden")

    suggestion = auto_calibration.suggest_room_size(sensor_id)
    if suggestion is None:
        n = auto_calibration.get_sample_count(sensor_id)
        raise HTTPException(
            425,
            f"Noch nicht genug Daten ({n}/{auto_calibration.MIN_SAMPLES} Messungen). "
            "Bitte im Raum bewegen."
        )

    room_id = sensor.get("room_id")
    rooms   = request.app.state.rooms
    room    = next((r for r in rooms if r["id"] == room_id), None)

    return {
        "sensor_id": sensor_id,
        "room_id":   room_id,
        "current": {
            "width_mm":  room.get("width_mm",  0) if room else 0,
            "height_mm": room.get("height_mm", 0) if room else 0,
        },
        **suggestion,
    }


class RoomSizeBody(BaseModel):
    width_mm:  int
    height_mm: int


@router.post("/sensors/{sensor_id}/auto-calibration/room-size/apply")
def apply_room_size(sensor_id: str, body: RoomSizeBody, request: Request):
    """Schreibt die geschätzten (oder vom Nutzer angepassten) Raummaße in rooms.json."""
    sensors = request.app.state.sensors
    sensor  = next((s for s in sensors if s["id"] == sensor_id), None)
    if sensor is None:
        raise HTTPException(404, f"Sensor '{sensor_id}' nicht gefunden")

    room_id = sensor.get("room_id")
    if not room_id:
        raise HTTPException(400, "Sensor hat keinen zugewiesenen Raum")

    if body.width_mm < 500 or body.height_mm < 500:
        raise HTTPException(422, "Raummaße müssen mindestens 500 mm betragen")

    rooms_path = CONFIG_DIR / "rooms.json"
    rooms_data = load_json(rooms_path)

    updated = False
    for room in rooms_data:
        if room["id"] == room_id:
            old_w, old_h = room.get("width_mm", 0), room.get("height_mm", 0)
            room["width_mm"]  = body.width_mm
            room["height_mm"] = body.height_mm
            logger.info(
                "Raumgröße aktualisiert: %s  %d×%d → %d×%d mm",
                room_id, old_w, old_h, body.width_mm, body.height_mm
            )
            updated = True
            break

    if not updated:
        raise HTTPException(404, f"Raum '{room_id}' nicht in rooms.json gefunden")

    save_json(rooms_path, rooms_data)

    from app.config import load_rooms, load_sensors
    request.app.state.rooms   = load_rooms()
    request.app.state.sensors = load_sensors(request.app.state.rooms)

    return {
        "status":    "ok",
        "room_id":   room_id,
        "width_mm":  body.width_mm,
        "height_mm": body.height_mm,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Datenpuffer zurücksetzen
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/sensors/{sensor_id}/auto-calibration/reset")
def reset_buffer(sensor_id: str):
    """Löscht den gesammelten Datenpuffer für einen Sensor."""
    auto_calibration.reset(sensor_id)
    logger.info("Auto-Kalibrierungs-Puffer gelöscht: %s", sensor_id)
    return {"status": "ok", "sensor_id": sensor_id}
