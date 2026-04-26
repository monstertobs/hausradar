"""
GET /api/history/positions – gespeicherte Zielpositionen
GET /api/history/sessions  – Aktivitätsphasen pro Raum
GET /api/history/events    – Sensor-Online/Offline-Ereignisse
"""

from typing import Optional

from fastapi import APIRouter, Query, Request

from app import database as db

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/positions")
def get_positions(
    request:   Request,
    sensor_id: Optional[str] = Query(default=None),
    room_id:   Optional[str] = Query(default=None),
    from_ms:   Optional[int] = Query(default=None),
    to_ms:     Optional[int] = Query(default=None),
    limit:     int           = Query(default=1000, ge=1, le=10000),
):
    return db.query_positions(
        request.app.state.db_path,
        sensor_id=sensor_id,
        room_id=room_id,
        from_ms=from_ms,
        to_ms=to_ms,
        limit=limit,
    )


@router.get("/sessions")
def get_sessions(
    request: Request,
    room_id: Optional[str] = Query(default=None),
    from_ms: Optional[int] = Query(default=None),
    to_ms:   Optional[int] = Query(default=None),
    limit:   int           = Query(default=200, ge=1, le=2000),
):
    return db.query_sessions(
        request.app.state.db_path,
        room_id=room_id,
        from_ms=from_ms,
        to_ms=to_ms,
        limit=limit,
    )


@router.get("/events")
def get_events(
    request:   Request,
    sensor_id: Optional[str] = Query(default=None),
    from_ms:   Optional[int] = Query(default=None),
    to_ms:     Optional[int] = Query(default=None),
    limit:     int           = Query(default=200, ge=1, le=2000),
):
    return db.query_sensor_events(
        request.app.state.db_path,
        sensor_id=sensor_id,
        from_ms=from_ms,
        to_ms=to_ms,
        limit=limit,
    )
