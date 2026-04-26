"""
Bewegungsprofile – Aggregationen über target_positions und motion_sessions.

Alle Funktionen lesen aus der SQLite-Datenbank und geben aufbereitete
Statistiken zurück. Zeitstempel werden in Ortszeit umgerechnet.
"""

import time
from typing import Any, Dict, List, Optional

from app.database import get_db


def _cutoff_ms(days: int) -> int:
    return int((time.time() - days * 86400) * 1000)


_ALLOWED_FILTER_COLUMNS = frozenset({"room_id", "sensor_id", "zone_id"})


def _where(base_clauses: List[str], extra: Dict[str, Any]) -> tuple:
    """Baut WHERE-Klausel und Parameterliste auf.
    Nur Spalten aus _ALLOWED_FILTER_COLUMNS sind erlaubt (HR-SEC-015)."""
    clauses = list(base_clauses)
    params: List[Any] = []
    for col, val in extra.items():
        if col not in _ALLOWED_FILTER_COLUMNS:
            raise ValueError(f"Ungültiger Filterparameter: {col!r}")
        if val is not None:
            clauses.append(f"{col} = ?")
            params.append(val)
    return "WHERE " + " AND ".join(clauses), params


# ---------------------------------------------------------------------------
# GET /api/profile/hourly
# ---------------------------------------------------------------------------

def hourly_activity(
    db_path: str,
    room_id:   Optional[str] = None,
    sensor_id: Optional[str] = None,
    days: int = 7,
) -> List[Dict[str, Any]]:
    """Aktivitätszähler pro Stunde (0–23) über alle angeforderten Tage."""
    cutoff = _cutoff_ms(days)
    extra = {}
    if room_id   is not None: extra["room_id"]   = room_id
    if sensor_id is not None: extra["sensor_id"] = sensor_id
    where, params = _where(["timestamp_ms >= ?"], extra)
    params = [cutoff] + params

    with get_db(db_path) as conn:
        rows = conn.execute(
            f"""SELECT
                CAST(strftime('%H', datetime(timestamp_ms/1000, 'unixepoch', 'localtime')) AS INTEGER) AS hour,
                COUNT(*) AS count
            FROM target_positions
            {where}
            GROUP BY hour
            ORDER BY hour""",
            params,
        ).fetchall()

    data = {r["hour"]: r["count"] for r in rows}
    return [{"hour": h, "count": data.get(h, 0)} for h in range(24)]


# ---------------------------------------------------------------------------
# GET /api/profile/heatmap
# ---------------------------------------------------------------------------

def heatmap(
    db_path: str,
    room_id: Optional[str] = None,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """7×24-Heatmap: Aktivität pro Wochentag (0=Mo … 6=So) und Stunde (0–23)."""
    cutoff = _cutoff_ms(days)
    extra = {}
    if room_id is not None: extra["room_id"] = room_id
    where, params = _where(["timestamp_ms >= ?"], extra)
    params = [cutoff] + params

    with get_db(db_path) as conn:
        rows = conn.execute(
            f"""SELECT
                CAST(strftime('%w', datetime(timestamp_ms/1000, 'unixepoch', 'localtime')) AS INTEGER) AS wd_sqlite,
                CAST(strftime('%H', datetime(timestamp_ms/1000, 'unixepoch', 'localtime')) AS INTEGER) AS hour,
                COUNT(*) AS count
            FROM target_positions
            {where}
            GROUP BY wd_sqlite, hour""",
            params,
        ).fetchall()

    # SQLite %w: 0=So, 1=Mo … 6=Sa → ISO: 0=Mo … 6=So
    data: Dict[tuple, int] = {}
    for r in rows:
        wd_iso = (r["wd_sqlite"] - 1) % 7
        data[(wd_iso, r["hour"])] = r["count"]

    return [
        {"weekday": wd, "hour": h, "count": data.get((wd, h), 0)}
        for wd in range(7)
        for h in range(24)
    ]


# ---------------------------------------------------------------------------
# GET /api/profile/zones
# ---------------------------------------------------------------------------

def zone_activity(
    db_path: str,
    room_id: Optional[str] = None,
    days: int = 7,
) -> List[Dict[str, Any]]:
    """Aktivitätshäufigkeit pro Zone, absteigend sortiert, mit Prozentanteil."""
    cutoff = _cutoff_ms(days)
    extra = {}
    if room_id is not None: extra["room_id"] = room_id
    where, params = _where(["timestamp_ms >= ?", "zone_id IS NOT NULL"], extra)
    params = [cutoff] + params

    with get_db(db_path) as conn:
        rows = conn.execute(
            f"""SELECT zone_id, room_id, COUNT(*) AS count
            FROM target_positions
            {where}
            GROUP BY zone_id, room_id
            ORDER BY count DESC""",
            params,
        ).fetchall()

    result = [dict(r) for r in rows]
    total = sum(r["count"] for r in result)
    for r in result:
        r["pct"] = round(r["count"] / total * 100, 1) if total > 0 else 0.0
    return result


# ---------------------------------------------------------------------------
# GET /api/profile/rooms
# ---------------------------------------------------------------------------

def room_activity(
    db_path: str,
    room_id: Optional[str] = None,
    days: int = 7,
) -> List[Dict[str, Any]]:
    """Session-Statistik pro Raum: Anzahl, Gesamtdauer, Durchschnittsdauer."""
    cutoff = _cutoff_ms(days)
    extra = {}
    if room_id is not None: extra["room_id"] = room_id
    where, params = _where(["started_at_ms >= ?"], extra)
    params = [cutoff] + params

    with get_db(db_path) as conn:
        rows = conn.execute(
            f"""SELECT
                room_id,
                COUNT(*) AS session_count,
                COALESCE(SUM(CASE WHEN ended_at_ms IS NOT NULL
                    THEN (ended_at_ms - started_at_ms) / 1000.0 END), 0.0) AS total_duration_s,
                COALESCE(AVG(CASE WHEN ended_at_ms IS NOT NULL
                    THEN (ended_at_ms - started_at_ms) / 1000.0 END), 0.0) AS avg_duration_s
            FROM motion_sessions
            {where}
            GROUP BY room_id
            ORDER BY session_count DESC""",
            params,
        ).fetchall()

    return [dict(r) for r in rows]
