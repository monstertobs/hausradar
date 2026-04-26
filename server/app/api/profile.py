"""
GET /api/profile/hourly   – Aktivität pro Stunde (0–23)
GET /api/profile/heatmap  – 7×24-Wochentag/Stunden-Heatmap
GET /api/profile/zones    – Aktivität pro Zone
GET /api/profile/rooms    – Session-Statistik pro Raum
"""

from typing import Optional

from fastapi import APIRouter, Query, Request

from app import analytics

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("/hourly")
def get_hourly(
    request:   Request,
    room_id:   Optional[str] = Query(default=None),
    sensor_id: Optional[str] = Query(default=None),
    days:      int           = Query(default=7, ge=1, le=365),
):
    return analytics.hourly_activity(
        request.app.state.db_path,
        room_id=room_id,
        sensor_id=sensor_id,
        days=days,
    )


@router.get("/heatmap")
def get_heatmap(
    request: Request,
    room_id: Optional[str] = Query(default=None),
    days:    int           = Query(default=30, ge=1, le=365),
):
    return analytics.heatmap(
        request.app.state.db_path,
        room_id=room_id,
        days=days,
    )


@router.get("/zones")
def get_zones(
    request: Request,
    room_id: Optional[str] = Query(default=None),
    days:    int           = Query(default=7, ge=1, le=365),
):
    return analytics.zone_activity(
        request.app.state.db_path,
        room_id=room_id,
        days=days,
    )


@router.get("/rooms")
def get_rooms(
    request: Request,
    room_id: Optional[str] = Query(default=None),
    days:    int           = Query(default=7, ge=1, le=365),
):
    return analytics.room_activity(
        request.app.state.db_path,
        room_id=room_id,
        days=days,
    )
