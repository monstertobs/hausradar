"""
Kalibrierungs-API für HausRadar.

Endpunkte:
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
from typing import Optional

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

    room_obj["width_mm"]  = new_w
    room_obj["height_mm"] = new_h

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
        "restart_required": True,
        "restart_hint": "sudo systemctl restart hausradar",
    }
