"""
Kalibrierungs-API für HausRadar.

Endpunkte:
  GET    /api/calibrate/overview                               → Alle gespeicherten Kalibrierungen
  PATCH  /api/calibrate/room/{room_id}                         → Raummaße anpassen
  PATCH  /api/calibrate/sensor/{sensor_id}                     → Sensorposition anpassen
  PATCH  /api/calibrate/room/{room_id}/furniture/{fid}         → Möbelstück anpassen
  PATCH  /api/calibrate/room/{room_id}/door/{did}              → Tür anpassen
  DELETE /api/calibrate/room/{room_id}/furniture/{fid}         → Einzelnes Möbelstück löschen
  DELETE /api/calibrate/room/{room_id}/furniture               → Alle Möbel eines Raums löschen
  DELETE /api/calibrate/room/{room_id}/door/{did}              → Tür löschen
  DELETE /api/calibrate/room/{room_id}/zone/{zone_id}          → Einzelne Zone löschen
  DELETE /api/calibrate/room/{room_id}/zones                   → Alle Zonen eines Raums löschen
  DELETE /api/calibrate/room/{room_id}/reset                   → Raum-Kalibrierung zurücksetzen

  POST   /api/calibrate/session                                → Session anlegen
  GET    /api/calibrate/session/{sid}                          → Session lesen
  DELETE /api/calibrate/session/{sid}                          → Session löschen
  POST   /api/calibrate/session/{sid}/mark/{label}             → Raumecke markieren
  POST   /api/calibrate/session/{sid}/compute                  → Raummaße berechnen
  POST   /api/calibrate/session/{sid}/furniture                → Möbelstück anlegen
  POST   /api/calibrate/session/{sid}/furniture/{fid}/mark/{c} → Möbelecke markieren
  POST   /api/calibrate/session/{sid}/furniture/{fid}/compute  → Möbelmaße berechnen
  POST   /api/calibrate/session/{sid}/save                     → In Config schreiben
"""

import json
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import live_state
from app import calibration_engine as engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/calibrate", tags=["calibrate"])

BASE_DIR    = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_DIR  = BASE_DIR / "config"


# ---------------------------------------------------------------------------
# Request-Modelle
# ---------------------------------------------------------------------------

class StartRequest(BaseModel):
    sensor_id: str
    room_id:   str


class FurnitureRequest(BaseModel):
    name:    str
    type:    str = "other"
    is_zone: bool = True


class DoorRequest(BaseModel):
    name:        str
    connects_to: str   # room_id des Zielraums


class PatchRoomRequest(BaseModel):
    width_mm:     Optional[int]              = None
    height_mm:    Optional[int]              = None
    shape_points: Optional[List[List[float]]] = None  # None = clear, list = set polygon


class PatchSensorRequest(BaseModel):
    x_mm:         Optional[float] = None
    y_mm:         Optional[float] = None
    rotation_deg: Optional[float] = None
    flip_x:       Optional[bool]  = None


class PatchFurnitureRequest(BaseModel):
    name:         Optional[str]   = None
    type:         Optional[str]   = None
    x_mm:         Optional[int]   = None
    y_mm:         Optional[int]   = None
    width_mm:     Optional[int]   = None
    height_mm:    Optional[int]   = None
    rotation_deg: Optional[float] = None


class PatchDoorRequest(BaseModel):
    name:         Optional[str] = None
    connects_to:  Optional[str] = None
    wall:         Optional[str] = None
    position_mm:  Optional[int] = None
    width_mm:     Optional[int] = None


class AddFurnitureDirectRequest(BaseModel):
    """Möbelstück direkt zu einem Raum hinzufügen (ohne Kalibrierungs-Session)."""
    name:      str
    type:      str  = "other"
    x_mm:      int
    y_mm:      int
    width_mm:  int
    height_mm: int
    is_zone:   bool = False


class AddDoorDirectRequest(BaseModel):
    """Tür direkt zu einem Raum hinzufügen (ohne Kalibrierungs-Session)."""
    name:        str
    connects_to: str  = ""
    wall:        str  = "top"
    position_mm: int  = 500
    width_mm:    int  = 900


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _get_session_or_404(session_id: str) -> dict:
    session = engine.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session nicht gefunden oder abgelaufen")
    return session


def _current_sensor_pos(sensor_id: str) -> dict:
    """
    Gibt die aktuelle Sensorposition (Sensor-Koordinaten) zurück.
    Wirft 503 wenn kein frischer Datenpunkt verfügbar ist.
    """
    elapsed = live_state.seconds_since(sensor_id)
    if elapsed is None or elapsed > 3.0:
        raise HTTPException(
            status_code=503,
            detail="Keine aktuellen Sensordaten verfügbar – ist der Sensor online?",
        )

    state = live_state.get(sensor_id)
    targets = (state or {}).get("targets", [])
    if not targets:
        raise HTTPException(
            status_code=503,
            detail="Kein Ziel erkannt – stelle sicher, dass du im Sichtfeld des Sensors stehst",
        )

    # Nimm das erste Ziel (Nutzer sollte allein im Raum sein)
    t = targets[0]
    return {"x_mm": t["x_mm"], "y_mm": t["y_mm"], "targets_total": len(targets)}


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

@router.post("/session", status_code=201)
def start_session(body: StartRequest, request: Request):
    """Startet eine neue Kalibrierungs-Session."""
    sensors = request.app.state.sensors
    rooms   = request.app.state.rooms

    if not any(s["id"] == body.sensor_id for s in sensors):
        raise HTTPException(status_code=404, detail=f"Sensor '{body.sensor_id}' nicht gefunden")
    if not any(r["id"] == body.room_id for r in rooms):
        raise HTTPException(status_code=404, detail=f"Raum '{body.room_id}' nicht gefunden")

    session_id = engine.create_session(body.sensor_id, body.room_id)
    logger.info("Kalibrierungs-Session %s gestartet (Sensor: %s, Raum: %s)",
                session_id, body.sensor_id, body.room_id)

    return {
        "session_id":      session_id,
        "corner_sequence": engine.CORNER_SEQUENCE,
        "corner_display":  engine.CORNER_DISPLAY,
        "furniture_types": engine.FURNITURE_TYPES,
    }


@router.get("/session/{session_id}")
def get_session(session_id: str):
    return _get_session_or_404(session_id)


@router.delete("/session/{session_id}", status_code=204)
def delete_session(session_id: str):
    engine.delete_session(session_id)


# ---------------------------------------------------------------------------
# Raumecken
# ---------------------------------------------------------------------------

@router.post("/session/{session_id}/mark/{label}")
def mark_corner(session_id: str, label: str):
    """
    Markiert die aktuelle Position des Sensors als Raumecke.
    Der Nutzer muss sich im Sichtfeld des Sensors befinden.
    """
    session = _get_session_or_404(session_id)
    pos = _current_sensor_pos(session["sensor_id"])

    try:
        engine.mark_corner(session_id, label, pos["x_mm"], pos["y_mm"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    session = engine.get_session(session_id)
    marked  = list(session["corners"].keys())
    remaining = [c for c in engine.CORNER_SEQUENCE if c not in marked]

    return {
        "label":          label,
        "x_mm":           pos["x_mm"],
        "y_mm":           pos["y_mm"],
        "targets_total":  pos["targets_total"],
        "marked_corners": marked,
        "remaining":      remaining,
        "all_marked":     len(remaining) == 0,
    }


@router.post("/session/{session_id}/compute")
def compute_room(session_id: str):
    """Berechnet Raummaße und Sensorposition aus den vier markierten Ecken."""
    _get_session_or_404(session_id)
    try:
        result = engine.compute_room(session_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return result


# ---------------------------------------------------------------------------
# Möbel
# ---------------------------------------------------------------------------

@router.post("/session/{session_id}/furniture", status_code=201)
def add_furniture(session_id: str, body: FurnitureRequest):
    """Legt ein neues Möbelstück in der Session an."""
    _get_session_or_404(session_id)
    fid = engine.add_furniture(session_id, body.name, body.type, body.is_zone)
    return {"furniture_id": fid}


@router.post("/session/{session_id}/furniture/{fid}/mark/{corner}")
def mark_furniture_corner(session_id: str, fid: str, corner: str):
    """
    Markiert die aktuelle Position als Ecke eines Möbelstücks.
    corner muss 'a' oder 'b' sein (diagonal gegenüberliegende Ecken).
    """
    session = _get_session_or_404(session_id)
    pos = _current_sensor_pos(session["sensor_id"])

    try:
        engine.mark_furniture_corner(session_id, fid, corner, pos["x_mm"], pos["y_mm"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    item = engine.get_furniture(session_id, fid)
    return {
        "furniture_id": fid,
        "corner":       corner,
        "x_mm":         pos["x_mm"],
        "y_mm":         pos["y_mm"],
        "corners_done": list(item["corners"].keys()),
        "ready":        len(item["corners"]) >= 2,
    }


@router.post("/session/{session_id}/furniture/{fid}/compute")
def compute_furniture(session_id: str, fid: str):
    """Berechnet Position und Abmessungen des Möbelstücks."""
    _get_session_or_404(session_id)
    try:
        result = engine.compute_furniture_pos(session_id, fid)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return result


# ---------------------------------------------------------------------------
# Einzelnen Eckpunkt nachkalibrieren
# ---------------------------------------------------------------------------

@router.post("/session/{session_id}/remark/{label}")
def remark_corner(session_id: str, label: str):
    """
    Überschreibt einen bereits markierten Eckpunkt mit der aktuellen Position.
    Setzt computed zurück – danach muss /compute erneut aufgerufen werden.
    """
    session = _get_session_or_404(session_id)
    pos = _current_sensor_pos(session["sensor_id"])

    try:
        engine.mark_corner(session_id, label, pos["x_mm"], pos["y_mm"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Bisherige Berechnung ungültig machen
    engine.get_session(session_id)["computed"] = None

    return {
        "label":    label,
        "x_mm":     pos["x_mm"],
        "y_mm":     pos["y_mm"],
        "recompute_required": True,
    }


# ---------------------------------------------------------------------------
# Türen
# ---------------------------------------------------------------------------

@router.post("/session/{session_id}/door", status_code=201)
def add_door(session_id: str, body: DoorRequest, request: Request):
    """Legt eine neue Tür in der Session an."""
    _get_session_or_404(session_id)
    rooms = request.app.state.rooms
    if not any(r["id"] == body.connects_to for r in rooms):
        raise HTTPException(status_code=404,
                            detail=f"Zielraum '{body.connects_to}' nicht gefunden")
    did = engine.add_door(session_id, body.name, body.connects_to)
    return {"door_id": did}


@router.post("/session/{session_id}/door/{did}/mark/{point}")
def mark_door_point(session_id: str, did: str, point: str):
    """
    Markiert die aktuelle Position als Türkante.
    point muss 'a' (eine Seite) oder 'b' (andere Seite) sein.
    """
    session = _get_session_or_404(session_id)
    pos = _current_sensor_pos(session["sensor_id"])

    try:
        engine.mark_door_point(session_id, did, point, pos["x_mm"], pos["y_mm"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    door = engine.get_door(session_id, did)
    return {
        "door_id":    did,
        "point":      point,
        "x_mm":       pos["x_mm"],
        "y_mm":       pos["y_mm"],
        "points_done": list(door["points"].keys()),
        "ready":       len(door["points"]) >= 2,
    }


@router.post("/session/{session_id}/door/{did}/compute")
def compute_door(session_id: str, did: str):
    """Berechnet Wand, Position und Breite der Tür."""
    _get_session_or_404(session_id)
    try:
        result = engine.compute_door(session_id, did)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return result


# ---------------------------------------------------------------------------
# Speichern
# ---------------------------------------------------------------------------

@router.post("/session/{session_id}/save")
def save_calibration(session_id: str, request: Request):
    """
    Schreibt die kalibrierten Werte in rooms.json und sensors.json.

    Was geändert wird:
      rooms.json:   width_mm, height_mm, furniture[], zones (aus is_zone-Möbeln)
      sensors.json: x_mm, y_mm, rotation_deg

    Der Dienst muss danach neu gestartet werden damit die Änderungen wirken.
    """
    session = _get_session_or_404(session_id)
    computed = session.get("computed")
    if not computed:
        raise HTTPException(status_code=422, detail="Raummaße noch nicht berechnet")

    sensor_id = session["sensor_id"]
    room_id   = session["room_id"]

    # --- rooms.json aktualisieren ---
    rooms_path = CONFIG_DIR / "rooms.json"
    try:
        rooms = json.loads(rooms_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"rooms.json lesen fehlgeschlagen: {e}")

    room_obj = next((r for r in rooms if r["id"] == room_id), None)
    if room_obj is None:
        raise HTTPException(status_code=404, detail=f"Raum '{room_id}' nicht in rooms.json")

    old_w = room_obj.get("width_mm", 0)
    old_h = room_obj.get("height_mm", 0)
    new_w = computed["width_mm"]
    new_h = computed["height_mm"]

    # Schutzvalidierung: negative Maße können durch falsche Eckenreihenfolge
    # entstehen – Absolutwert verwenden damit rooms.json valide bleibt.
    room_obj["width_mm"]  = max(abs(new_w),  1)
    room_obj["height_mm"] = max(abs(new_h),  1)

    # Möbel in furniture[] + ggf. zones[] schreiben
    furniture_list = room_obj.setdefault("furniture", [])
    zones_list     = room_obj.setdefault("zones", [])

    for furn in session["furniture"]:
        comp = furn.get("computed")
        if not comp:
            continue  # nicht berechnet → überspringen

        fobj = {
            "id":        furn["id"],
            "name":      furn["name"],
            "type":      furn["type"],
            "x_mm":      comp["x_mm"],
            "y_mm":      comp["y_mm"],
            "width_mm":  comp["width_mm"],
            "height_mm": comp["height_mm"],
        }

        # Vorhandenes Möbelstück mit gleicher id ersetzen
        furniture_list[:] = [f for f in furniture_list if f.get("id") != furn["id"]]
        furniture_list.append(fobj)

        if furn["is_zone"]:
            zone = {
                "id":        furn["id"],
                "name":      furn["name"],
                "x_mm":      comp["x_mm"],
                "y_mm":      comp["y_mm"],
                "width_mm":  comp["width_mm"],
                "height_mm": comp["height_mm"],
            }
            zones_list[:] = [z for z in zones_list if z.get("id") != furn["id"]]
            zones_list.append(zone)

    # Türen in doors[] schreiben
    doors_list = room_obj.setdefault("doors", [])
    for door in session.get("doors", []):
        dcomp = door.get("computed")
        if not dcomp:
            continue
        dobj = {
            "id":           door["id"],
            "name":         door["name"],
            "connects_to":  door["connects_to"],
            "wall":         dcomp["wall"],
            "position_mm":  dcomp["position_mm"],
            "width_mm":     dcomp["width_mm"],
        }
        doors_list[:] = [d for d in doors_list if d.get("id") != door["id"]]
        doors_list.append(dobj)

    try:
        rooms_path.write_text(
            json.dumps(rooms, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"rooms.json schreiben fehlgeschlagen: {e}")

    # --- sensors.json aktualisieren ---
    sensors_path = CONFIG_DIR / "sensors.json"
    try:
        sensors = json.loads(sensors_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"sensors.json lesen fehlgeschlagen: {e}")

    sensor_obj = next((s for s in sensors if s["id"] == sensor_id), None)
    if sensor_obj is None:
        raise HTTPException(status_code=404, detail=f"Sensor '{sensor_id}' nicht in sensors.json")

    sensor_obj["x_mm"]        = computed["sensor_x_mm"]
    sensor_obj["y_mm"]        = computed["sensor_y_mm"]
    sensor_obj["rotation_deg"] = computed["rotation_deg"]

    try:
        sensors_path.write_text(
            json.dumps(sensors, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"sensors.json schreiben fehlgeschlagen: {e}")

    logger.info(
        "Kalibrierung gespeichert: Raum=%s (%.0f×%.0f mm, war %.0f×%.0f mm), "
        "Sensor=%s (x=%.0f y=%.0f rot=%.1f°), %d Möbelstück(e)",
        room_id, new_w, new_h, old_w, old_h,
        sensor_id, computed["sensor_x_mm"], computed["sensor_y_mm"], computed["rotation_deg"],
        len([f for f in session["furniture"] if f.get("computed")]),
    )

    engine.delete_session(session_id)

    return {
        "saved":   True,
        "room":    {"id": room_id,   "width_mm": new_w, "height_mm": new_h},
        "sensor":  {
            "id":           sensor_id,
            "x_mm":         computed["sensor_x_mm"],
            "y_mm":         computed["sensor_y_mm"],
            "rotation_deg": computed["rotation_deg"],
        },
        "furniture_saved": len([f for f in session["furniture"] if f.get("computed")]),
        "doors_saved":      len([d for d in session.get("doors", []) if d.get("computed")]),
        "restart_required": True,
        "restart_hint": "sudo systemctl restart hausradar",
    }


# ---------------------------------------------------------------------------
# Übersicht gespeicherter Kalibrierungen
# ---------------------------------------------------------------------------

def _load_json_file(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{path.name} lesen fehlgeschlagen: {e}")


def _write_json_file(path: Path, data) -> None:
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{path.name} schreiben fehlgeschlagen: {e}")


@router.get("/overview")
def get_overview():
    """
    Gibt alle gespeicherten Kalibrierungen zurück – kombiniert aus
    rooms.json (Raummaße, Möbel) und sensors.json (Sensorposition).
    """
    rooms   = _load_json_file(CONFIG_DIR / "rooms.json")
    sensors = _load_json_file(CONFIG_DIR / "sensors.json")

    sensor_by_room: dict = {}
    for s in sensors:
        rid = s.get("room_id")
        if rid:
            sensor_by_room.setdefault(rid, []).append({
                "id":           s.get("id"),
                "name":         s.get("name"),
                "x_mm":         s.get("x_mm"),
                "y_mm":         s.get("y_mm"),
                "rotation_deg": s.get("rotation_deg"),
                "flip_x":       s.get("flip_x", False),
                "enabled":      s.get("enabled", True),
            })

    result = []
    for room in rooms:
        rid = room.get("id")
        entry = {
            "id":        rid,
            "name":      room.get("name"),
            "width_mm":  room.get("width_mm"),
            "height_mm": room.get("height_mm"),
            "furniture": room.get("furniture", []),
            "doors":     room.get("doors", []),
            "zones":     room.get("zones", []),
            "sensors":   sensor_by_room.get(rid, []),
        }
        if "shape_points" in room:
            entry["shape_points"] = room["shape_points"]
        result.append(entry)

    return result


# ---------------------------------------------------------------------------
# Möbel löschen
# ---------------------------------------------------------------------------

@router.delete("/room/{room_id}/furniture/{furniture_id}", status_code=200)
def delete_furniture_item(room_id: str, furniture_id: str):
    """Löscht ein einzelnes Möbelstück (und die zugehörige Zone) aus rooms.json."""
    rooms_path = CONFIG_DIR / "rooms.json"
    rooms = _load_json_file(rooms_path)

    room = next((r for r in rooms if r["id"] == room_id), None)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Raum '{room_id}' nicht gefunden")

    before_furn  = len(room.get("furniture", []))
    before_zones = len(room.get("zones", []))

    room["furniture"] = [f for f in room.get("furniture", []) if f.get("id") != furniture_id]
    room["zones"]     = [z for z in room.get("zones", [])     if z.get("id") != furniture_id]

    deleted_furn  = before_furn  - len(room["furniture"])
    deleted_zones = before_zones - len(room["zones"])

    if deleted_furn == 0:
        raise HTTPException(status_code=404,
                            detail=f"Möbelstück '{furniture_id}' nicht in Raum '{room_id}'")

    _write_json_file(rooms_path, rooms)
    logger.info("Möbelstück '%s' aus Raum '%s' gelöscht (%d Zone(n) mitgelöscht)",
                furniture_id, room_id, deleted_zones)

    return {
        "deleted":       furniture_id,
        "zones_removed": deleted_zones,
        "restart_required": True,
        "restart_hint":  "sudo systemctl restart hausradar",
    }


@router.delete("/room/{room_id}/door/{door_id}", status_code=200)
def delete_door(room_id: str, door_id: str):
    """Löscht eine einzelne Tür aus rooms.json."""
    rooms_path = CONFIG_DIR / "rooms.json"
    rooms = _load_json_file(rooms_path)

    room = next((r for r in rooms if r["id"] == room_id), None)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Raum '{room_id}' nicht gefunden")

    before = len(room.get("doors", []))
    room["doors"] = [d for d in room.get("doors", []) if d.get("id") != door_id]

    if len(room["doors"]) == before:
        raise HTTPException(status_code=404,
                            detail=f"Tür '{door_id}' nicht in Raum '{room_id}'")

    _write_json_file(rooms_path, rooms)
    logger.info("Tür '%s' aus Raum '%s' gelöscht", door_id, room_id)
    return {"deleted": door_id, "restart_required": True,
            "restart_hint": "sudo systemctl restart hausradar"}


@router.delete("/room/{room_id}/furniture", status_code=200)
def delete_all_furniture(room_id: str):
    """Löscht alle Möbel eines Raums. Zonen die aus Möbeln stammen werden ebenfalls entfernt."""
    rooms_path = CONFIG_DIR / "rooms.json"
    rooms = _load_json_file(rooms_path)

    room = next((r for r in rooms if r["id"] == room_id), None)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Raum '{room_id}' nicht gefunden")

    furniture = room.get("furniture", [])
    furn_ids  = {f.get("id") for f in furniture}
    count     = len(furniture)

    room["furniture"] = []
    # Nur Zonen entfernen die aus Möbeln stammen (gleiche id)
    room["zones"] = [z for z in room.get("zones", []) if z.get("id") not in furn_ids]

    _write_json_file(rooms_path, rooms)
    logger.info("Alle %d Möbelstück(e) aus Raum '%s' gelöscht", count, room_id)

    return {
        "deleted_count":    count,
        "restart_required": True,
        "restart_hint":     "sudo systemctl restart hausradar",
    }


@router.delete("/room/{room_id}/zone/{zone_id}", status_code=200)
def delete_zone(room_id: str, zone_id: str):
    """Löscht eine einzelne Zone aus rooms.json."""
    rooms_path = CONFIG_DIR / "rooms.json"
    rooms = _load_json_file(rooms_path)

    room = next((r for r in rooms if r["id"] == room_id), None)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Raum '{room_id}' nicht gefunden")

    before = len(room.get("zones", []))
    room["zones"] = [z for z in room.get("zones", []) if z.get("id") != zone_id]

    if len(room["zones"]) == before:
        raise HTTPException(status_code=404,
                            detail=f"Zone '{zone_id}' nicht in Raum '{room_id}'")

    _write_json_file(rooms_path, rooms)
    logger.info("Zone '%s' aus Raum '%s' gelöscht", zone_id, room_id)
    return {"deleted": zone_id, "restart_required": True,
            "restart_hint": "sudo systemctl restart hausradar"}


@router.delete("/room/{room_id}/zones", status_code=200)
def delete_all_zones(room_id: str):
    """Löscht alle Zonen eines Raums (unabhängig davon, ob sie aus Möbeln stammen)."""
    rooms_path = CONFIG_DIR / "rooms.json"
    rooms = _load_json_file(rooms_path)

    room = next((r for r in rooms if r["id"] == room_id), None)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Raum '{room_id}' nicht gefunden")

    count = len(room.get("zones", []))
    room["zones"] = []

    _write_json_file(rooms_path, rooms)
    logger.info("Alle %d Zone(n) aus Raum '%s' gelöscht", count, room_id)
    return {"deleted_count": count, "restart_required": True,
            "restart_hint": "sudo systemctl restart hausradar"}


# ---------------------------------------------------------------------------
# Raum-Kalibrierung zurücksetzen
# ---------------------------------------------------------------------------

@router.delete("/room/{room_id}/reset", status_code=200)
def reset_room_calibration(room_id: str):
    """
    Setzt die Kalibrierung eines Raums zurück:
      - Möbel und daraus entstandene Zonen werden gelöscht
      - Raummaße bleiben erhalten (nur Möbel/Zonen)
      - Sensorposition wird auf Standardwerte zurückgesetzt (x=width/2, y=0, rotation=0)
    """
    rooms_path   = CONFIG_DIR / "rooms.json"
    sensors_path = CONFIG_DIR / "sensors.json"

    rooms   = _load_json_file(rooms_path)
    sensors = _load_json_file(sensors_path)

    room = next((r for r in rooms if r["id"] == room_id), None)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Raum '{room_id}' nicht gefunden")

    # Möbel-IDs sammeln um zugehörige Zonen zu löschen
    furn_ids = {f.get("id") for f in room.get("furniture", [])}
    furn_count = len(room.get("furniture", []))

    room["furniture"] = []
    room["zones"]     = [z for z in room.get("zones", []) if z.get("id") not in furn_ids]

    _write_json_file(rooms_path, rooms)

    # Sensoren dieses Raums auf Standardposition zurücksetzen
    reset_sensors = []
    default_x = round(room.get("width_mm", 0) / 2)
    for sensor in sensors:
        if sensor.get("room_id") == room_id:
            sensor["x_mm"]         = default_x
            sensor["y_mm"]         = 0
            sensor["rotation_deg"] = 0
            sensor.pop("flip_x", None)
            reset_sensors.append(sensor["id"])

    _write_json_file(sensors_path, sensors)

    logger.info(
        "Kalibrierung von Raum '%s' zurückgesetzt: %d Möbel gelöscht, %d Sensor(en) resettet",
        room_id, furn_count, len(reset_sensors),
    )

    return {
        "room_id":          room_id,
        "furniture_deleted": furn_count,
        "sensors_reset":    reset_sensors,
        "restart_required": True,
        "restart_hint":     "sudo systemctl restart hausradar",
    }


# ---------------------------------------------------------------------------
# Einzelne Messwerte bearbeiten (PATCH)
# ---------------------------------------------------------------------------

@router.post("/room/{room_id}/furniture", status_code=201)
def add_furniture_direct(room_id: str, body: AddFurnitureDirectRequest):
    """Fügt ein Möbelstück direkt zu einem Raum hinzu (ohne Kalibrierungs-Session)."""
    valid_walls = {"top", "bottom", "left", "right"}
    rooms_path = CONFIG_DIR / "rooms.json"
    rooms = _load_json_file(rooms_path)
    room = next((r for r in rooms if r["id"] == room_id), None)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Raum '{room_id}' nicht gefunden")

    if body.width_mm <= 0 or body.height_mm <= 0:
        raise HTTPException(status_code=422, detail="width_mm und height_mm müssen positiv sein")

    import uuid
    furn_id = str(uuid.uuid4())[:8]

    furn_entry = {
        "id":         furn_id,
        "name":       body.name,
        "type":       body.type,
        "x_mm":       body.x_mm,
        "y_mm":       body.y_mm,
        "width_mm":   body.width_mm,
        "height_mm":  body.height_mm,
    }

    room.setdefault("furniture", []).append(furn_entry)

    # Als Zone eintragen wenn gewünscht
    if body.is_zone:
        zone_entry = {
            "id":        furn_id,
            "name":      body.name,
            "x_mm":      body.x_mm,
            "y_mm":      body.y_mm,
            "width_mm":  body.width_mm,
            "height_mm": body.height_mm,
        }
        room.setdefault("zones", []).append(zone_entry)

    _write_json_file(rooms_path, rooms)
    logger.info("Möbelstück '%s' direkt zu Raum '%s' hinzugefügt", furn_id, room_id)
    return {"room_id": room_id, "furniture_id": furn_id, "restart_required": True,
            "restart_hint": "sudo systemctl restart hausradar"}


@router.post("/room/{room_id}/door", status_code=201)
def add_door_direct(room_id: str, body: AddDoorDirectRequest):
    """Fügt eine Tür direkt zu einem Raum hinzu (ohne Kalibrierungs-Session)."""
    valid_walls = {"top", "bottom", "left", "right"}
    if body.wall not in valid_walls:
        raise HTTPException(status_code=422,
                            detail=f"Ungültige Wand '{body.wall}' – erlaubt: {valid_walls}")

    rooms_path = CONFIG_DIR / "rooms.json"
    rooms = _load_json_file(rooms_path)
    room = next((r for r in rooms if r["id"] == room_id), None)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Raum '{room_id}' nicht gefunden")

    if body.width_mm <= 0:
        raise HTTPException(status_code=422, detail="width_mm muss positiv sein")
    if body.position_mm < 0:
        raise HTTPException(status_code=422, detail="position_mm darf nicht negativ sein")

    import uuid
    door_id = str(uuid.uuid4())[:8]

    door_entry = {
        "id":           door_id,
        "name":         body.name,
        "connects_to":  body.connects_to,
        "wall":         body.wall,
        "position_mm":  body.position_mm,
        "width_mm":     body.width_mm,
    }

    room.setdefault("doors", []).append(door_entry)
    _write_json_file(rooms_path, rooms)
    logger.info("Tür '%s' direkt zu Raum '%s' hinzugefügt", door_id, room_id)
    return {"room_id": room_id, "door_id": door_id, "restart_required": True,
            "restart_hint": "sudo systemctl restart hausradar"}


@router.patch("/room/{room_id}", status_code=200)
def patch_room(room_id: str, body: PatchRoomRequest, request: Request):
    """Ändert Raummaße (width_mm, height_mm) direkt in rooms.json."""
    rooms_path = CONFIG_DIR / "rooms.json"
    rooms = _load_json_file(rooms_path)
    room = next((r for r in rooms if r["id"] == room_id), None)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Raum '{room_id}' nicht gefunden")

    updated = {}
    if body.width_mm is not None:
        if body.width_mm <= 0:
            raise HTTPException(status_code=422, detail="width_mm muss positiv sein")
        room["width_mm"] = body.width_mm
        updated["width_mm"] = body.width_mm
    if body.height_mm is not None:
        if body.height_mm <= 0:
            raise HTTPException(status_code=422, detail="height_mm muss positiv sein")
        room["height_mm"] = body.height_mm
        updated["height_mm"] = body.height_mm
    if "shape_points" in body.model_fields_set:
        if body.shape_points is None:
            room.pop("shape_points", None)
            updated["shape_points"] = None
        elif len(body.shape_points) < 3:
            raise HTTPException(status_code=422, detail="shape_points braucht mindestens 3 Punkte")
        else:
            room["shape_points"] = [[float(p[0]), float(p[1])] for p in body.shape_points]
            updated["shape_points"] = f"{len(body.shape_points)} Punkte"

    if not updated:
        raise HTTPException(status_code=422, detail="Keine Felder zum Aktualisieren angegeben")

    _write_json_file(rooms_path, rooms)
    request.app.state.rooms = rooms
    logger.info("Raum '%s' gepatcht: %s", room_id, updated)
    return {"room_id": room_id, "updated": updated, "restart_required": True,
            "restart_hint": "sudo systemctl restart hausradar"}


@router.patch("/sensor/{sensor_id}", status_code=200)
def patch_sensor(sensor_id: str, body: PatchSensorRequest):
    """Ändert Sensorposition/-rotation direkt in sensors.json."""
    sensors_path = CONFIG_DIR / "sensors.json"
    sensors = _load_json_file(sensors_path)
    sensor = next((s for s in sensors if s["id"] == sensor_id), None)
    if sensor is None:
        raise HTTPException(status_code=404, detail=f"Sensor '{sensor_id}' nicht gefunden")

    updated = {}
    if body.x_mm is not None:
        sensor["x_mm"] = round(body.x_mm, 1)
        updated["x_mm"] = sensor["x_mm"]
    if body.y_mm is not None:
        sensor["y_mm"] = round(body.y_mm, 1)
        updated["y_mm"] = sensor["y_mm"]
    if body.rotation_deg is not None:
        sensor["rotation_deg"] = round(body.rotation_deg, 1)
        updated["rotation_deg"] = sensor["rotation_deg"]
    if body.flip_x is not None:
        if body.flip_x:
            sensor["flip_x"] = True
        else:
            sensor.pop("flip_x", None)
        updated["flip_x"] = body.flip_x

    if not updated:
        raise HTTPException(status_code=422, detail="Keine Felder zum Aktualisieren angegeben")

    _write_json_file(sensors_path, sensors)
    logger.info("Sensor '%s' gepatcht: %s", sensor_id, updated)
    return {"sensor_id": sensor_id, "updated": updated, "restart_required": True,
            "restart_hint": "sudo systemctl restart hausradar"}


@router.patch("/room/{room_id}/furniture/{fid}", status_code=200)
def patch_furniture(room_id: str, fid: str, body: PatchFurnitureRequest, request: Request):
    """Ändert ein Möbelstück direkt in rooms.json."""
    rooms_path = CONFIG_DIR / "rooms.json"
    rooms = _load_json_file(rooms_path)
    room = next((r for r in rooms if r["id"] == room_id), None)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Raum '{room_id}' nicht gefunden")

    furn = next((f for f in room.get("furniture", []) if f.get("id") == fid), None)
    # Auch in zones suchen (is_zone-Möbel landen dort)
    zone = next((z for z in room.get("zones", []) if z.get("id") == fid), None)

    if furn is None and zone is None:
        raise HTTPException(status_code=404, detail=f"Möbelstück '{fid}' nicht gefunden")

    updated = {}
    for target in [x for x in (furn, zone) if x is not None]:
        if body.name is not None:
            target["name"] = body.name;  updated["name"] = body.name
        if body.type is not None and target is furn:
            target["type"] = body.type;  updated["type"] = body.type
        if body.x_mm is not None:
            target["x_mm"] = body.x_mm;  updated["x_mm"] = body.x_mm
        if body.y_mm is not None:
            target["y_mm"] = body.y_mm;  updated["y_mm"] = body.y_mm
        if body.width_mm is not None:
            target["width_mm"] = body.width_mm;  updated["width_mm"] = body.width_mm
        if body.height_mm is not None:
            target["height_mm"] = body.height_mm; updated["height_mm"] = body.height_mm
        if body.rotation_deg is not None and target is furn:
            target["rotation_deg"] = body.rotation_deg; updated["rotation_deg"] = body.rotation_deg

    if not updated:
        raise HTTPException(status_code=422, detail="Keine Felder zum Aktualisieren angegeben")

    _write_json_file(rooms_path, rooms)
    request.app.state.rooms = rooms
    logger.info("Möbelstück '%s' in Raum '%s' gepatcht: %s", fid, room_id, updated)
    return {"room_id": room_id, "furniture_id": fid, "updated": updated,
            "restart_required": True, "restart_hint": "sudo systemctl restart hausradar"}


@router.patch("/room/{room_id}/door/{did}", status_code=200)
def patch_door(room_id: str, did: str, body: PatchDoorRequest, request: Request):
    """Ändert eine Tür direkt in rooms.json."""
    valid_walls = {"top", "bottom", "left", "right"}
    if body.wall is not None and body.wall not in valid_walls:
        raise HTTPException(status_code=422,
                            detail=f"Ungültige Wand '{body.wall}' – erlaubt: {valid_walls}")

    rooms_path = CONFIG_DIR / "rooms.json"
    rooms = _load_json_file(rooms_path)
    room = next((r for r in rooms if r["id"] == room_id), None)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Raum '{room_id}' nicht gefunden")

    door = next((d for d in room.get("doors", []) if d.get("id") == did), None)
    if door is None:
        raise HTTPException(status_code=404, detail=f"Tür '{did}' nicht gefunden")

    updated = {}
    if body.name is not None:
        door["name"] = body.name;               updated["name"] = body.name
    if body.connects_to is not None:
        door["connects_to"] = body.connects_to; updated["connects_to"] = body.connects_to
    if body.wall is not None:
        door["wall"] = body.wall;               updated["wall"] = body.wall
    if body.position_mm is not None:
        door["position_mm"] = body.position_mm; updated["position_mm"] = body.position_mm
    if body.width_mm is not None:
        door["width_mm"] = body.width_mm;       updated["width_mm"] = body.width_mm

    if not updated:
        raise HTTPException(status_code=422, detail="Keine Felder zum Aktualisieren angegeben")

    _write_json_file(rooms_path, rooms)
    request.app.state.rooms = rooms
    logger.info("Tür '%s' in Raum '%s' gepatcht: %s", did, room_id, updated)
    return {"room_id": room_id, "door_id": did, "updated": updated,
            "restart_required": True, "restart_hint": "sudo systemctl restart hausradar"}


# ---------------------------------------------------------------------------
# Grundriss-Auto-Layout  (POST /api/calibrate/layout)
# ---------------------------------------------------------------------------

@router.post("/layout", status_code=200)
def compute_and_save_layout():
    """
    Berechnet SVG-Floorplan-Koordinaten für alle Räume neu:
    BFS-Traversal des Türgraphen → angrenzende Räume werden an der passenden
    Wand platziert, sodass die Türöffnung ungefähr fluchtet.

    Räume ohne Türverbindung landen in einer Reihe unterhalb des Hauptgraphen.

    Schreibt die neuen floorplan-Koordinaten in rooms.json.
    """
    SCALE = 0.05   # px / mm (1 m → 50 px – konsistent mit bisherigen Daten)
    GAP   = 12     # px Lücke zwischen benachbarten Räumen
    PAD   = 10     # px Außenabstand

    rooms_path = CONFIG_DIR / "rooms.json"
    rooms = _load_json_file(rooms_path)

    if not rooms:
        return {"placed": 0, "message": "Keine Räume vorhanden"}

    room_map = {r["id"]: r for r in rooms}

    def fp_size(room):
        w = max(round(room.get("width_mm",  5000) * SCALE), 20)
        h = max(round(room.get("height_mm", 4000) * SCALE), 20)
        return w, h

    placed  = {}          # room_id → (fp_x, fp_y)
    visited = set()

    # BFS-Start: erster Raum
    first_id = rooms[0]["id"]
    placed[first_id]  = (PAD, PAD)
    visited.add(first_id)
    queue = [first_id]

    while queue:
        rid  = queue.pop(0)
        room = room_map[rid]
        rx, ry = placed[rid]
        rw, rh = fp_size(room)

        for door in room.get("doors", []):
            nid = (door.get("connects_to") or "").strip()
            if not nid or nid not in room_map or nid in visited:
                continue

            neighbor    = room_map[nid]
            nw, nh      = fp_size(neighbor)
            wall        = door.get("wall", "right")
            door_pos    = door.get("position_mm", 0) * SCALE
            door_w      = door.get("width_mm", 800)  * SCALE
            door_center = door_pos + door_w / 2

            # Nachbar so platzieren, dass Türmitte im Nachbar der Türmitte im
            # aktuellen Raum entspricht (grobe Ausrichtung)
            if wall == "right":
                nx = rx + rw + GAP
                ny = ry + door_center - nh / 2
            elif wall == "left":
                nx = rx - GAP - nw
                ny = ry + door_center - nh / 2
            elif wall == "bottom":
                ny = ry + rh + GAP
                nx = rx + door_center - nw / 2
            elif wall == "top":
                ny = ry - GAP - nh
                nx = rx + door_center - nw / 2
            else:
                nx = rx + rw + GAP
                ny = ry

            placed[nid] = (round(nx), round(ny))
            visited.add(nid)
            queue.append(nid)

    # Räume ohne Verbindung: Reihe unterhalb des Hauptgraphen
    if placed:
        max_y = max(y + fp_size(room_map[r])[1] for r, (x, y) in placed.items())
    else:
        max_y = PAD
    cur_x = PAD
    for room in rooms:
        if room["id"] not in placed:
            nw, nh = fp_size(room)
            placed[room["id"]] = (cur_x, round(max_y + GAP * 3))
            cur_x += nw + GAP

    # Normalisieren: alles so verschieben, dass min_x = PAD, min_y = PAD
    min_x = min(x for x, y in placed.values())
    min_y = min(y for x, y in placed.values())
    sx, sy = PAD - min_x, PAD - min_y
    placed = {rid: (x + sx, y + sy) for rid, (x, y) in placed.items()}

    # In rooms.json schreiben
    for room in rooms:
        rid = room["id"]
        if rid not in placed:
            continue
        fx, fy = placed[rid]
        fw, fh = fp_size(room)
        room["floorplan"] = {"x": fx, "y": fy, "width": fw, "height": fh}

    _write_json_file(rooms_path, rooms)
    logger.info("Grundriss-Auto-Layout: %d Räume platziert", len(placed))

    return {
        "placed":           len(placed),
        "layout":           {rid: {"x": x, "y": y, "w": fp_size(room_map[rid])[0],
                                   "h": fp_size(room_map[rid])[1]}
                             for rid, (x, y) in placed.items()},
        "restart_required": True,
        "restart_hint":     "sudo systemctl restart hausradar",
    }
