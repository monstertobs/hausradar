"""
REST-API für Möbel-Erkennungs-Zonen (M22).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app import furniture_detector

router = APIRouter()


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/furniture/zones
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/furniture/zones")
def list_zones(room_id: Optional[str] = None):
    """Alle Dwell-Zonen zurückgeben (optional gefiltert nach room_id)."""
    return {"zones": furniture_detector.get_zones(room_id)}


# ──────────────────────────────────────────────────────────────────────────────
# DELETE /api/furniture/zones/{zone_id}
# ──────────────────────────────────────────────────────────────────────────────

@router.delete("/furniture/zones/{zone_id}")
def remove_zone(zone_id: str):
    if not furniture_detector.delete_zone(zone_id):
        raise HTTPException(status_code=404, detail="Zone nicht gefunden")
    return {"status": "ok"}


# ──────────────────────────────────────────────────────────────────────────────
# DELETE /api/furniture/zones  (alle Zonen eines Raums)
# ──────────────────────────────────────────────────────────────────────────────

@router.delete("/furniture/zones")
def clear_zones(room_id: str):
    removed = furniture_detector.clear_room(room_id)
    return {"status": "ok", "removed": removed}


# ──────────────────────────────────────────────────────────────────────────────
# PATCH /api/furniture/zones/{zone_id}  – Möbeltyp manuell bestätigen
# ──────────────────────────────────────────────────────────────────────────────

class ZonePatch(BaseModel):
    confirmed_type: str
    label: Optional[str] = None


@router.patch("/furniture/zones/{zone_id}")
def patch_zone(zone_id: str, body: ZonePatch):
    """Ermöglicht, den vorgeschlagenen Typ manuell zu bestätigen."""
    zones = furniture_detector.get_zones()
    with furniture_detector._lock:
        for z in furniture_detector._zones:
            if z["id"] == zone_id:
                z["confirmed_type"] = body.confirmed_type
                if body.label is not None:
                    z["label"] = body.label
                furniture_detector._save()
                return {"status": "ok", "zone_id": zone_id}
    raise HTTPException(status_code=404, detail="Zone nicht gefunden")


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/furniture/prune
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/furniture/prune")
def prune():
    removed = furniture_detector.prune_old_zones()
    return {"status": "ok", "removed": removed}
