"""
Sensoren-API für HausRadar.

Endpunkte:
  GET    /api/sensors                  → Alle Sensoren (aus app.state)
  PATCH  /api/sensors/{sensor_id}      → Name / enabled / Montagehöhe ändern
  POST   /api/sensors                  → Neuen Sensor anlegen
  DELETE /api/sensors/{sensor_id}      → Sensor löschen
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config_io import load_json, save_json

logger = logging.getLogger(__name__)
router = APIRouter()

BASE_DIR   = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"


def _unique_id(base: str, used: set) -> str:
    sid = base
    n = 2
    while sid in used:
        sid = f"{base}_{n}"
        n += 1
    return sid


# ---------------------------------------------------------------------------
# GET /api/sensors
# ---------------------------------------------------------------------------

@router.get("/sensors")
def get_sensors(request: Request):
    return request.app.state.sensors


# ---------------------------------------------------------------------------
# PATCH /api/sensors/{sensor_id}  – Metadaten ändern
# ---------------------------------------------------------------------------

class PatchSensorBody(BaseModel):
    name:            Optional[str]  = None
    enabled:         Optional[bool] = None
    mount_height_mm: Optional[int]  = None


@router.patch("/sensors/{sensor_id}", status_code=200)
def patch_sensor_meta(sensor_id: str, body: PatchSensorBody, request: Request):
    sensors_path = CONFIG_DIR / "sensors.json"
    sensors = load_json(sensors_path)
    sensor = next((s for s in sensors if s["id"] == sensor_id), None)
    if not sensor:
        raise HTTPException(status_code=404, detail=f"Sensor '{sensor_id}' nicht gefunden")

    updated = {}
    if body.name is not None:
        sensor["name"] = body.name.strip()
        updated["name"] = sensor["name"]
    if body.enabled is not None:
        sensor["enabled"] = body.enabled
        updated["enabled"] = body.enabled
    if body.mount_height_mm is not None:
        sensor["mount_height_mm"] = body.mount_height_mm
        updated["mount_height_mm"] = body.mount_height_mm

    if not updated:
        raise HTTPException(status_code=422, detail="Keine Felder angegeben")

    save_json(sensors_path, sensors)
    request.app.state.sensors = sensors
    logger.info("Sensor '%s' gepatcht: %s", sensor_id, updated)
    return {"sensor_id": sensor_id, "updated": updated}


# ---------------------------------------------------------------------------
# POST /api/sensors  – Neuen Sensor anlegen
# ---------------------------------------------------------------------------

class CreateSensorBody(BaseModel):
    name:            str
    room_id:         str
    x_mm:            int   = 0
    y_mm:            int   = 0
    rotation_deg:    float = 0.0
    mount_height_mm: int   = 2200


@router.post("/sensors", status_code=201)
def create_sensor(body: CreateSensorBody, request: Request):
    rooms_path   = CONFIG_DIR / "rooms.json"
    sensors_path = CONFIG_DIR / "sensors.json"
    rooms   = load_json(rooms_path)
    sensors = load_json(sensors_path)

    room = next((r for r in rooms if r["id"] == body.room_id), None)
    if not room:
        raise HTTPException(status_code=404, detail=f"Raum '{body.room_id}' nicht gefunden")

    sid = _unique_id(f"radar_{body.room_id}", {s["id"] for s in sensors})
    new_sensor = {
        "id":              sid,
        "name":            body.name.strip(),
        "room_id":         body.room_id,
        "x_mm":            body.x_mm,
        "y_mm":            body.y_mm,
        "mount_height_mm": body.mount_height_mm,
        "rotation_deg":    body.rotation_deg,
        "enabled":         True,
    }
    sensors.append(new_sensor)
    save_json(sensors_path, sensors)
    request.app.state.sensors = sensors

    logger.info("Sensor '%s' angelegt für Raum '%s'", sid, body.room_id)
    return {"sensor": new_sensor}


# ---------------------------------------------------------------------------
# DELETE /api/sensors/{sensor_id}  – Sensor löschen
# ---------------------------------------------------------------------------

@router.delete("/sensors/{sensor_id}", status_code=200)
def delete_sensor(sensor_id: str, request: Request):
    sensors_path = CONFIG_DIR / "sensors.json"
    sensors = load_json(sensors_path)
    sensor = next((s for s in sensors if s["id"] == sensor_id), None)
    if not sensor:
        raise HTTPException(status_code=404, detail=f"Sensor '{sensor_id}' nicht gefunden")

    sensors = [s for s in sensors if s["id"] != sensor_id]
    save_json(sensors_path, sensors)
    request.app.state.sensors = sensors

    logger.info("Sensor '%s' gelöscht", sensor_id)
    return {"sensor_id": sensor_id}
