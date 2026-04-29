"""
Räume-API für HausRadar.

Endpunkte:
  GET    /api/rooms                → Alle Räume (aus app.state)
  PATCH  /api/rooms/{room_id}      → Raum umbenennen
  POST   /api/rooms                → Neuen Raum (+ optionalen Sensor) anlegen
  DELETE /api/rooms/{room_id}      → Raum + zugehörige Sensoren löschen
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

BASE_DIR   = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"

# Maßstab px/mm – muss mit rooms.json übereinstimmen (1 m → 50 px)
SCALE_PX_PER_MM = 0.05
FP_PAD = 10   # px Außenabstand


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _load(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _slugify(name: str) -> str:
    """Name → maschinenlesbarer Bezeichner (lowercase ASCII)."""
    s = name.lower()
    for src, dst in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")]:
        s = s.replace(src, dst)
    s = re.sub(r"[^a-z0-9_]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "raum"


def _unique_id(base: str, used: set) -> str:
    """Gibt base zurück wenn frei, sonst base_2, base_3, …"""
    rid = base
    n = 2
    while rid in used:
        rid = f"{base}_{n}"
        n += 1
    return rid


# ---------------------------------------------------------------------------
# GET /api/rooms
# ---------------------------------------------------------------------------

@router.get("/rooms")
def get_rooms(request: Request):
    return request.app.state.rooms


# ---------------------------------------------------------------------------
# PATCH /api/rooms/{room_id}  – Raum umbenennen
# ---------------------------------------------------------------------------

class PatchRoomBody(BaseModel):
    name: Optional[str] = None


@router.patch("/rooms/{room_id}", status_code=200)
def patch_room(room_id: str, body: PatchRoomBody):
    rooms_path = CONFIG_DIR / "rooms.json"
    rooms = _load(rooms_path)
    room = next((r for r in rooms if r["id"] == room_id), None)
    if not room:
        raise HTTPException(status_code=404, detail=f"Raum '{room_id}' nicht gefunden")

    updated = {}
    if body.name is not None:
        room["name"] = body.name.strip()
        updated["name"] = room["name"]

    if not updated:
        raise HTTPException(status_code=422, detail="Keine Felder zum Aktualisieren angegeben")

    _save(rooms_path, rooms)
    logger.info("Raum '%s' umbenannt: %s", room_id, updated)
    return {
        "room_id":         room_id,
        "updated":         updated,
        "restart_required": True,
        "restart_hint":    "sudo systemctl restart hausradar",
    }


# ---------------------------------------------------------------------------
# POST /api/rooms  – Neuen Raum anlegen
# ---------------------------------------------------------------------------

class CreateRoomBody(BaseModel):
    name:        str
    width_mm:    int            = 5000
    height_mm:   int            = 4000
    sensor_name: Optional[str] = None


@router.post("/rooms", status_code=201)
def create_room(body: CreateRoomBody):
    rooms_path   = CONFIG_DIR / "rooms.json"
    sensors_path = CONFIG_DIR / "sensors.json"
    rooms   = _load(rooms_path)
    sensors = _load(sensors_path)

    # Raum-ID aus Namen ableiten
    rid = _unique_id(_slugify(body.name.strip()), {r["id"] for r in rooms})

    # Floorplan-Position: rechts neben dem rechtesten bestehenden Raum
    if rooms:
        right_edge = max(
            r.get("floorplan", {}).get("x", FP_PAD) + r.get("floorplan", {}).get("width", 0)
            for r in rooms
        )
    else:
        right_edge = FP_PAD

    fp_x = right_edge + FP_PAD
    fp_y = FP_PAD
    fp_w = max(round(body.width_mm  * SCALE_PX_PER_MM), 20)
    fp_h = max(round(body.height_mm * SCALE_PX_PER_MM), 20)

    new_room = {
        "id":        rid,
        "name":      body.name.strip(),
        "width_mm":  body.width_mm,
        "height_mm": body.height_mm,
        "floorplan": {"x": fp_x, "y": fp_y, "width": fp_w, "height": fp_h},
        "zones":     [],
        "furniture": [],
        "doors":     [],
    }
    rooms.append(new_room)
    _save(rooms_path, rooms)

    # Optionalen Sensor anlegen
    sensor_out = None
    if body.sensor_name:
        sid = _unique_id(f"radar_{rid}", {s["id"] for s in sensors})
        new_sensor = {
            "id":              sid,
            "name":            body.sensor_name.strip(),
            "room_id":         rid,
            "x_mm":            round(body.width_mm / 2),
            "y_mm":            0,
            "mount_height_mm": 2200,
            "rotation_deg":    0,
            "enabled":         True,
        }
        sensors.append(new_sensor)
        _save(sensors_path, sensors)
        sensor_out = new_sensor
        logger.info("Sensor '%s' angelegt für Raum '%s'", sid, rid)

    logger.info("Neuer Raum '%s' angelegt", rid)
    return {
        "room":            new_room,
        "sensor":          sensor_out,
        "restart_required": True,
        "restart_hint":    "sudo systemctl restart hausradar",
    }


# ---------------------------------------------------------------------------
# DELETE /api/rooms/{room_id}  – Raum + Sensoren löschen
# ---------------------------------------------------------------------------

@router.delete("/rooms/{room_id}", status_code=200)
def delete_room(room_id: str):
    rooms_path   = CONFIG_DIR / "rooms.json"
    sensors_path = CONFIG_DIR / "sensors.json"
    rooms   = _load(rooms_path)
    sensors = _load(sensors_path)

    room = next((r for r in rooms if r["id"] == room_id), None)
    if not room:
        raise HTTPException(status_code=404, detail=f"Raum '{room_id}' nicht gefunden")

    removed_sensors = [s["id"] for s in sensors if s.get("room_id") == room_id]
    rooms   = [r for r in rooms   if r["id"]          != room_id]
    sensors = [s for s in sensors if s.get("room_id") != room_id]

    # Türverweise auf gelöschten Raum leeren
    for r in rooms:
        for door in r.get("doors", []):
            if door.get("connects_to") == room_id:
                door["connects_to"] = ""

    _save(rooms_path, rooms)
    _save(sensors_path, sensors)

    logger.info("Raum '%s' gelöscht, %d Sensor(en) entfernt", room_id, len(removed_sensors))
    return {
        "room_id":         room_id,
        "sensors_removed": removed_sensors,
        "restart_required": True,
        "restart_hint":    "sudo systemctl restart hausradar",
    }
