"""
API-Endpunkte für automatische Türerkennung.

GET  /api/doors/suggestions  – aktuelle Tür-Kandidaten
GET  /api/doors/stats        – Anzahl gesammelter Events
POST /api/doors/confirm      – Tür-Kandidat bestätigen → schreibt in rooms.json
DELETE /api/doors/events     – alle Events löschen (Reset)
"""

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import door_detector

logger = logging.getLogger(__name__)
router = APIRouter()

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/doors/suggestions
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/doors/suggestions")
def get_suggestions(request: Request):
    rooms = request.app.state.rooms
    suggestions = door_detector.get_suggestions(rooms)

    # Raumnamen für leads_to ergänzen
    room_name_map = {r["id"]: r["name"] for r in rooms}
    for s in suggestions:
        lt = s.get("leads_to")
        if lt and lt != "outside":
            s["leads_to_name"] = room_name_map.get(lt, lt)
        elif lt == "outside":
            s["leads_to_name"] = "Außenbereich / Terrasse"
        else:
            s["leads_to_name"] = None

    return {"suggestions": suggestions, "stats": door_detector.get_stats()}


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/doors/stats
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/doors/stats")
def get_stats():
    return door_detector.get_stats()


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/doors/confirm
# ──────────────────────────────────────────────────────────────────────────────

class ConfirmDoorBody(BaseModel):
    room_id:     str
    wall:        str
    position_mm: int
    width_mm:    int   = 900
    leads_to:    Optional[str] = None  # room_id | "outside" | None


@router.post("/doors/confirm")
def confirm_door(body: ConfirmDoorBody, request: Request):
    """
    Fügt eine erkannte Tür zu rooms.json hinzu.
    Eine Tür wird als Door-Objekt in beide verbundenen Räume eingetragen.
    """
    rooms_path = CONFIG_DIR / "rooms.json"
    with open(rooms_path, encoding="utf-8") as f:
        rooms = json.load(f)

    room = next((r for r in rooms if r["id"] == body.room_id), None)
    if not room:
        raise HTTPException(404, f"Raum '{body.room_id}' nicht gefunden")

    # Tür-Objekt bauen
    door_id = f"auto_{body.room_id}_{body.wall}_{body.position_mm}"
    new_door = {
        "id":          door_id,
        "wall":        body.wall,
        "position_mm": body.position_mm,
        "width_mm":    body.width_mm,
        "leads_to":    body.leads_to,
    }

    # Prüfen ob Tür an dieser Position schon existiert
    existing = room.setdefault("doors", [])
    for d in existing:
        if d.get("wall") == body.wall and abs(d.get("position_mm", 0) - body.position_mm) < 300:
            raise HTTPException(409, "An dieser Wandposition existiert bereits eine Tür")

    existing.append(new_door)

    # Auch im Zielraum eintragen (gespiegelte Tür)
    if body.leads_to and body.leads_to != "outside":
        target_room = next((r for r in rooms if r["id"] == body.leads_to), None)
        if target_room:
            opposite = {"top": "bottom", "bottom": "top",
                        "left": "right",  "right": "left"}.get(body.wall, body.wall)
            target_door = {
                "id":          f"auto_{body.leads_to}_{opposite}_{body.position_mm}",
                "wall":        opposite,
                "position_mm": body.position_mm,
                "width_mm":    body.width_mm,
                "leads_to":    body.room_id,
            }
            target_room.setdefault("doors", []).append(target_door)

    with open(rooms_path, "w", encoding="utf-8") as f:
        json.dump(rooms, f, ensure_ascii=False, indent=2)

    # app.state direkt aktualisieren
    request.app.state.rooms = rooms

    logger.info("Tür bestätigt: %s / %s @ %dmm → %s",
                body.room_id, body.wall, body.position_mm, body.leads_to)

    return {"status": "ok", "door_id": door_id}


# ──────────────────────────────────────────────────────────────────────────────
# DELETE /api/doors/events
# ──────────────────────────────────────────────────────────────────────────────

@router.delete("/doors/events")
def clear_events():
    """Löscht alle gesammelten Exit- und Entry-Events."""
    door_detector.clear_events()
    return {"status": "ok"}
