"""
SQLite-Persistenzschicht für HausRadar.

Tabellen:
  target_positions  – Positionsdaten aller erkannten Ziele (rate-limited)
  motion_sessions   – Aktivitätsphasen pro Raum (Start/Ende)
  sensor_events     – Online-/Offline-Ereignisse pro Sensor
"""

import sqlite3
import time
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Modul-globaler Zustand (GIL-sicher für dict-Operationen)
_last_write_mono: Dict[str, float] = {}
_room_sessions:   Dict[str, Dict[str, Any]] = {}  # room_id → {session_id, max_targets}


def _reset_for_tests() -> None:
    """Rate-Limiter und Session-Cache zurücksetzen. Nur in Tests verwenden."""
    _last_write_mono.clear()
    _room_sessions.clear()


def _clear_tables_for_tests(db_path: str) -> None:
    """Alle Tabelleninhalte löschen. Nur in Tests verwenden."""
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM target_positions")
        conn.execute("DELETE FROM motion_sessions")
        conn.execute("DELETE FROM sensor_events")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db(db_path: str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path), timeout=5) as conn:
        # WAL-Mode: erlaubt gleichzeitige Lesezugriffe während eines Writes.
        # NORMAL: fsync nur bei Checkpoints – ausreichend für Heimserver.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS target_positions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                sensor_id    TEXT    NOT NULL,
                room_id      TEXT    NOT NULL,
                target_id    INTEGER NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                room_x_mm    REAL,
                room_y_mm    REAL,
                zone_id      TEXT,
                speed_mm_s   REAL,
                distance_mm  REAL
            );
            CREATE INDEX IF NOT EXISTS idx_tp_sensor_ts
                ON target_positions(sensor_id, timestamp_ms);
            CREATE INDEX IF NOT EXISTS idx_tp_room_ts
                ON target_positions(room_id, timestamp_ms);

            CREATE TABLE IF NOT EXISTS motion_sessions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id       TEXT    NOT NULL,
                started_at_ms INTEGER NOT NULL,
                ended_at_ms   INTEGER,
                max_targets   INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_ms_room
                ON motion_sessions(room_id, started_at_ms);

            CREATE TABLE IF NOT EXISTS sensor_events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                sensor_id    TEXT    NOT NULL,
                event_type   TEXT    NOT NULL,
                timestamp_ms INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_se_sensor_ts
                ON sensor_events(sensor_id, timestamp_ms);
        """)

        # Zombie-Sessions schließen: bei einem Absturz oder ungeplanten Neustart
        # bleiben Sessions mit ended_at_ms=NULL übrig. Wir setzen sie auf "jetzt".
        now_ms = int(time.time() * 1000)
        closed = conn.execute(
            "UPDATE motion_sessions SET ended_at_ms=? WHERE ended_at_ms IS NULL",
            (now_ms,),
        ).rowcount
        if closed:
            logger.info(
                "Datenbank: %d offene Session(s) beim Start geschlossen", closed
            )

    logger.info("Datenbank initialisiert: %s", db_path)


# ---------------------------------------------------------------------------
# Verbindungs-Helfer
# ---------------------------------------------------------------------------

def check_db(db_path: str) -> bool:
    """Gibt True zurück wenn die Datenbank erreichbar und lesbar ist."""
    try:
        with get_db(db_path) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


@contextmanager
def get_db(db_path: str):
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schreiben
# ---------------------------------------------------------------------------

def _rate_ok(sensor_id: str, max_per_second: float) -> bool:
    now  = time.monotonic()
    last = _last_write_mono.get(sensor_id, float("-inf"))
    min_interval = 1.0 / max_per_second if max_per_second > 0 else 0.0
    if now - last >= min_interval:
        _last_write_mono[sensor_id] = now
        return True
    return False


def record_motion(
    db_path: str,
    sensor_id: str,
    room_id: str,
    timestamp_ms: int,
    targets: List[Dict[str, Any]],
    max_writes_per_second: float,
) -> None:
    if not _rate_ok(sensor_id, max_writes_per_second):
        return

    inside = [t for t in targets if t.get("inside_room")]
    target_count = len(inside)

    with get_db(db_path) as conn:
        for t in inside:
            conn.execute(
                """INSERT INTO target_positions
                   (sensor_id, room_id, target_id, timestamp_ms,
                    room_x_mm, room_y_mm, zone_id, speed_mm_s, distance_mm)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    sensor_id, room_id, t["id"], timestamp_ms,
                    t.get("room_x_mm"), t.get("room_y_mm"),
                    t.get("zone_id"),
                    t.get("speed_mm_s"), t.get("distance_mm"),
                ),
            )

        # Session-Verwaltung
        if target_count > 0:
            if room_id not in _room_sessions:
                cur = conn.execute(
                    "INSERT INTO motion_sessions (room_id, started_at_ms, max_targets)"
                    " VALUES (?,?,?)",
                    (room_id, timestamp_ms, target_count),
                )
                _room_sessions[room_id] = {
                    "session_id": cur.lastrowid,
                    "max_targets": target_count,
                }
            elif target_count > _room_sessions[room_id]["max_targets"]:
                _room_sessions[room_id]["max_targets"] = target_count
                conn.execute(
                    "UPDATE motion_sessions SET max_targets=? WHERE id=?",
                    (target_count, _room_sessions[room_id]["session_id"]),
                )
        else:
            if room_id in _room_sessions:
                conn.execute(
                    "UPDATE motion_sessions SET ended_at_ms=? WHERE id=?",
                    (timestamp_ms, _room_sessions[room_id]["session_id"]),
                )
                del _room_sessions[room_id]


def record_sensor_event(
    db_path: str,
    sensor_id: str,
    event_type: str,
    timestamp_ms: int,
) -> None:
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO sensor_events (sensor_id, event_type, timestamp_ms)"
            " VALUES (?,?,?)",
            (sensor_id, event_type, timestamp_ms),
        )


def cleanup_old_data(db_path: str, retention_days: int) -> int:
    cutoff_ms = int((time.time() - retention_days * 86400) * 1000)
    total = 0
    with get_db(db_path) as conn:
        total += conn.execute(
            "DELETE FROM target_positions WHERE timestamp_ms < ?",
            (cutoff_ms,),
        ).rowcount
        total += conn.execute(
            "DELETE FROM motion_sessions"
            " WHERE started_at_ms < ? AND ended_at_ms IS NOT NULL",
            (cutoff_ms,),
        ).rowcount
        total += conn.execute(
            "DELETE FROM sensor_events WHERE timestamp_ms < ?",
            (cutoff_ms,),
        ).rowcount
    if total:
        logger.info(
            "Datenbereinigung: %d Zeilen gelöscht (älter als %d Tage)",
            total, retention_days,
        )
    return total


# ---------------------------------------------------------------------------
# Abfragen
# ---------------------------------------------------------------------------

def query_positions(
    db_path: str,
    sensor_id: Optional[str] = None,
    room_id:   Optional[str] = None,
    from_ms:   Optional[int] = None,
    to_ms:     Optional[int] = None,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params:  List[Any] = []
    if sensor_id is not None: clauses.append("sensor_id = ?");    params.append(sensor_id)
    if room_id   is not None: clauses.append("room_id = ?");      params.append(room_id)
    if from_ms   is not None: clauses.append("timestamp_ms >= ?"); params.append(from_ms)
    if to_ms     is not None: clauses.append("timestamp_ms <= ?"); params.append(to_ms)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with get_db(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM target_positions {where}"
            " ORDER BY timestamp_ms DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def query_sessions(
    db_path: str,
    room_id: Optional[str] = None,
    from_ms: Optional[int] = None,
    to_ms:   Optional[int] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params:  List[Any] = []
    if room_id is not None: clauses.append("room_id = ?");        params.append(room_id)
    if from_ms is not None: clauses.append("started_at_ms >= ?"); params.append(from_ms)
    if to_ms   is not None: clauses.append("started_at_ms <= ?"); params.append(to_ms)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with get_db(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM motion_sessions {where}"
            " ORDER BY started_at_ms DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def query_sensor_events(
    db_path: str,
    sensor_id: Optional[str] = None,
    from_ms:   Optional[int] = None,
    to_ms:     Optional[int] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params:  List[Any] = []
    if sensor_id is not None: clauses.append("sensor_id = ?");    params.append(sensor_id)
    if from_ms   is not None: clauses.append("timestamp_ms >= ?"); params.append(from_ms)
    if to_ms     is not None: clauses.append("timestamp_ms <= ?"); params.append(to_ms)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with get_db(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM sensor_events {where}"
            " ORDER BY timestamp_ms DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]
