"""
API-Endpunkte für gelernte Raum-zu-Raum-Verbindungen.

GET    /api/connections              – alle gelernten Verbindungen
DELETE /api/connections/{id}         – Verbindung löschen
POST   /api/connections/{id}/reset   – Zähler zurücksetzen
GET    /api/sensors/orientations     – Montage-Schätzungen aller Sensoren
GET    /api/sensors/{id}/orientation – Montage-Schätzung eines Sensors
"""

import logging

from fastapi import APIRouter, HTTPException

from app import transition_detector, orientation_detector

logger = logging.getLogger(__name__)
router = APIRouter()


# ──────────────────────────────────────────────────────────────────────────────
# Verbindungen
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/connections")
def get_connections():
    conns = transition_detector.get_connections()
    return {"connections": conns, "count": len(conns)}


@router.delete("/connections/{conn_id}")
def delete_connection(conn_id: str):
    if not transition_detector.delete_connection(conn_id):
        raise HTTPException(404, f"Verbindung '{conn_id}' nicht gefunden")
    logger.info("Gelernte Verbindung gelöscht: %s", conn_id)
    return {"status": "ok"}


@router.post("/connections/{conn_id}/reset")
def reset_connection(conn_id: str):
    if not transition_detector.reset_connection(conn_id):
        raise HTTPException(404, f"Verbindung '{conn_id}' nicht gefunden")
    logger.info("Gelernte Verbindung zurückgesetzt: %s", conn_id)
    return {"status": "ok"}


# ──────────────────────────────────────────────────────────────────────────────
# Sensor-Montage-Orientierung
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/sensors/orientations")
def get_all_orientations():
    return {"orientations": orientation_detector.get_all_orientations()}


@router.get("/sensors/{sensor_id}/orientation")
def get_orientation(sensor_id: str):
    result = orientation_detector.get_orientation(sensor_id)
    if result is None:
        raise HTTPException(
            404,
            f"Noch keine ausreichenden Daten für Sensor '{sensor_id}' "
            f"(min. {orientation_detector.MIN_SAMPLES} Messungen nötig)"
        )
    return result
