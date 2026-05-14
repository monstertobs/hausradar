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
        suggestion = auto_calibration.suggest(sid, room) if room else None
        result.append({
            "sensor_id":    sid,
            "sensor_name":  sensor.get("name", sid),
            "room_id":      sensor.get("room_id"),
            "sample_count": n,
            "min_samples":  auto_calibration.MIN_SAMPLES,
            "ready":        n >= auto_calibration.MIN_SAMPLES,
            "suggestion":   suggestion,
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
# Datenpuffer zurücksetzen
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/sensors/{sensor_id}/auto-calibration/reset")
def reset_buffer(sensor_id: str):
    """Löscht den gesammelten Datenpuffer für einen Sensor."""
    auto_calibration.reset(sensor_id)
    logger.info("Auto-Kalibrierungs-Puffer gelöscht: %s", sensor_id)
    return {"status": "ok", "sensor_id": sensor_id}
