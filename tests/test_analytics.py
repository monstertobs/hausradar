"""Tests für server/app/analytics.py und GET /api/profile/*."""
import sys
import time
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from fastapi.testclient import TestClient
from app.main import app
from app import analytics
from app import database as db
from app import live_state


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_state():
    db._reset_for_tests()
    yield
    db._reset_for_tests()


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    db.init_db(path)
    return path


@pytest.fixture()
def client():
    with TestClient(app) as c:
        db._clear_tables_for_tests(app.state.db_path)
        db._reset_for_tests()
        live_state.clear()
        yield c


def _ms(days_ago: float = 0, hour: int = 12, weekday_offset: int = 0) -> int:
    """Erzeugt einen Timestamp mit definiertem Alter und Tageszeit."""
    now = time.time()
    return int((now - days_ago * 86400 - (12 - hour) * 3600 - weekday_offset * 86400) * 1000)


def _insert_position(conn, sensor_id="s1", room_id="r1", target_id=1,
                     timestamp_ms=None, zone_id="z1",
                     room_x=100.0, room_y=100.0):
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)
    conn.execute(
        """INSERT INTO target_positions
           (sensor_id, room_id, target_id, timestamp_ms, room_x_mm, room_y_mm, zone_id)
           VALUES (?,?,?,?,?,?,?)""",
        (sensor_id, room_id, target_id, timestamp_ms, room_x, room_y, zone_id),
    )


def _insert_session(conn, room_id="r1", started_ms=None, ended_ms=None, max_targets=1):
    if started_ms is None:
        started_ms = int(time.time() * 1000) - 60_000
    if ended_ms is None:
        ended_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO motion_sessions (room_id, started_at_ms, ended_at_ms, max_targets)"
        " VALUES (?,?,?,?)",
        (room_id, started_ms, ended_ms, max_targets),
    )


# ---------------------------------------------------------------------------
# hourly_activity
# ---------------------------------------------------------------------------

class TestHourlyActivity:
    def test_empty_db_returns_24_hours(self, db_path):
        result = analytics.hourly_activity(db_path)
        assert len(result) == 24
        assert all(r["count"] == 0 for r in result)
        assert [r["hour"] for r in result] == list(range(24))

    def test_counts_positions_by_hour(self, db_path):
        now_ms = int(time.time() * 1000)
        with db.get_db(db_path) as conn:
            # Stunde aus dem aktuellen Timestamp holen
            import datetime
            current_hour = datetime.datetime.now().hour
            for _ in range(3):
                _insert_position(conn, timestamp_ms=now_ms)
        result = analytics.hourly_activity(db_path)
        assert result[current_hour]["count"] == 3

    def test_filter_by_room(self, db_path):
        with db.get_db(db_path) as conn:
            _insert_position(conn, room_id="r1")
            _insert_position(conn, room_id="r2")
        r1 = analytics.hourly_activity(db_path, room_id="r1")
        r2 = analytics.hourly_activity(db_path, room_id="r2")
        assert sum(r["count"] for r in r1) == 1
        assert sum(r["count"] for r in r2) == 1

    def test_filter_by_sensor(self, db_path):
        with db.get_db(db_path) as conn:
            _insert_position(conn, sensor_id="s1")
            _insert_position(conn, sensor_id="s2")
        result = analytics.hourly_activity(db_path, sensor_id="s1")
        assert sum(r["count"] for r in result) == 1

    def test_days_filter_excludes_old_data(self, db_path):
        with db.get_db(db_path) as conn:
            _insert_position(conn, timestamp_ms=_ms(days_ago=1))   # gestern
            _insert_position(conn, timestamp_ms=_ms(days_ago=10))  # vor 10 Tagen
        result = analytics.hourly_activity(db_path, days=7)
        assert sum(r["count"] for r in result) == 1

    def test_structure(self, db_path):
        result = analytics.hourly_activity(db_path)
        assert all("hour" in r and "count" in r for r in result)


# ---------------------------------------------------------------------------
# heatmap
# ---------------------------------------------------------------------------

class TestHeatmap:
    def test_empty_db_returns_168_cells(self, db_path):
        result = analytics.heatmap(db_path)
        assert len(result) == 7 * 24

    def test_all_cells_zero_when_empty(self, db_path):
        result = analytics.heatmap(db_path)
        assert all(r["count"] == 0 for r in result)

    def test_covers_all_weekday_hour_combos(self, db_path):
        result = analytics.heatmap(db_path)
        combos = {(r["weekday"], r["hour"]) for r in result}
        assert len(combos) == 168
        assert all(0 <= wd <= 6 for wd, _ in combos)
        assert all(0 <= h <= 23  for _, h  in combos)

    def test_counts_appear_in_correct_cell(self, db_path):
        import datetime
        now = datetime.datetime.now()
        wd_iso = (now.weekday())  # 0=Mo
        h = now.hour
        with db.get_db(db_path) as conn:
            _insert_position(conn, timestamp_ms=int(time.time() * 1000))
        result = analytics.heatmap(db_path)
        cell = next(r for r in result if r["weekday"] == wd_iso and r["hour"] == h)
        assert cell["count"] == 1

    def test_filter_by_room(self, db_path):
        with db.get_db(db_path) as conn:
            _insert_position(conn, room_id="r1")
            _insert_position(conn, room_id="r2")
        r1 = analytics.heatmap(db_path, room_id="r1")
        assert sum(r["count"] for r in r1) == 1

    def test_days_filter(self, db_path):
        with db.get_db(db_path) as conn:
            _insert_position(conn, timestamp_ms=_ms(days_ago=1))
            _insert_position(conn, timestamp_ms=_ms(days_ago=40))
        result = analytics.heatmap(db_path, days=30)
        assert sum(r["count"] for r in result) == 1


# ---------------------------------------------------------------------------
# zone_activity
# ---------------------------------------------------------------------------

class TestZoneActivity:
    def test_empty_db_returns_empty_list(self, db_path):
        assert analytics.zone_activity(db_path) == []

    def test_null_zone_excluded(self, db_path):
        with db.get_db(db_path) as conn:
            _insert_position(conn, zone_id=None)
        assert analytics.zone_activity(db_path) == []

    def test_counts_per_zone(self, db_path):
        with db.get_db(db_path) as conn:
            for _ in range(3):
                _insert_position(conn, zone_id="tv")
            _insert_position(conn, zone_id="couch")
        result = analytics.zone_activity(db_path)
        assert len(result) == 2
        assert result[0]["zone_id"] == "tv"
        assert result[0]["count"] == 3

    def test_pct_sums_to_100(self, db_path):
        with db.get_db(db_path) as conn:
            for _ in range(3):
                _insert_position(conn, zone_id="tv")
            for _ in range(7):
                _insert_position(conn, zone_id="couch")
        result = analytics.zone_activity(db_path)
        total_pct = sum(r["pct"] for r in result)
        assert abs(total_pct - 100.0) < 0.2

    def test_filter_by_room(self, db_path):
        with db.get_db(db_path) as conn:
            _insert_position(conn, room_id="r1", zone_id="z1")
            _insert_position(conn, room_id="r2", zone_id="z2")
        result = analytics.zone_activity(db_path, room_id="r1")
        assert len(result) == 1
        assert result[0]["zone_id"] == "z1"

    def test_days_filter(self, db_path):
        with db.get_db(db_path) as conn:
            _insert_position(conn, zone_id="z1", timestamp_ms=_ms(days_ago=1))
            _insert_position(conn, zone_id="z1", timestamp_ms=_ms(days_ago=10))
        result = analytics.zone_activity(db_path, days=7)
        assert result[0]["count"] == 1

    def test_structure(self, db_path):
        with db.get_db(db_path) as conn:
            _insert_position(conn, zone_id="z1")
        result = analytics.zone_activity(db_path)
        assert "zone_id" in result[0]
        assert "room_id" in result[0]
        assert "count"   in result[0]
        assert "pct"     in result[0]


# ---------------------------------------------------------------------------
# room_activity
# ---------------------------------------------------------------------------

class TestRoomActivity:
    def test_empty_db_returns_empty_list(self, db_path):
        assert analytics.room_activity(db_path) == []

    def test_counts_sessions(self, db_path):
        with db.get_db(db_path) as conn:
            _insert_session(conn, room_id="r1")
            _insert_session(conn, room_id="r1")
            _insert_session(conn, room_id="r2")
        result = analytics.room_activity(db_path)
        r1 = next(r for r in result if r["room_id"] == "r1")
        assert r1["session_count"] == 2

    def test_computes_duration(self, db_path):
        now_ms = int(time.time() * 1000)
        with db.get_db(db_path) as conn:
            _insert_session(conn, room_id="r1",
                            started_ms=now_ms - 60_000,
                            ended_ms=now_ms)
        result = analytics.room_activity(db_path)
        r1 = result[0]
        assert abs(r1["total_duration_s"] - 60.0) < 1.0
        assert abs(r1["avg_duration_s"]   - 60.0) < 1.0

    def test_open_sessions_excluded_from_duration(self, db_path):
        now_ms = int(time.time() * 1000)
        with db.get_db(db_path) as conn:
            # Abgeschlossene Session: 30s
            _insert_session(conn, room_id="r1",
                            started_ms=now_ms - 30_000,
                            ended_ms=now_ms)
            # Offene Session: kein ended_at_ms
            conn.execute(
                "INSERT INTO motion_sessions (room_id, started_at_ms) VALUES (?,?)",
                ("r1", now_ms - 10_000),
            )
        result = analytics.room_activity(db_path)
        r1 = result[0]
        assert r1["session_count"] == 2
        # Nur die abgeschlossene zählt zur Durchschnittsdauer
        assert abs(r1["avg_duration_s"] - 30.0) < 1.0

    def test_filter_by_room(self, db_path):
        with db.get_db(db_path) as conn:
            _insert_session(conn, room_id="r1")
            _insert_session(conn, room_id="r2")
        result = analytics.room_activity(db_path, room_id="r1")
        assert len(result) == 1
        assert result[0]["room_id"] == "r1"

    def test_days_filter(self, db_path):
        now_ms = int(time.time() * 1000)
        old_ms = int((time.time() - 10 * 86400) * 1000)
        with db.get_db(db_path) as conn:
            _insert_session(conn, room_id="r1",
                            started_ms=now_ms - 60_000, ended_ms=now_ms)
            _insert_session(conn, room_id="r1",
                            started_ms=old_ms, ended_ms=old_ms + 60_000)
        result = analytics.room_activity(db_path, days=7)
        assert result[0]["session_count"] == 1

    def test_sorted_by_session_count(self, db_path):
        with db.get_db(db_path) as conn:
            _insert_session(conn, room_id="r2")
            for _ in range(3):
                _insert_session(conn, room_id="r1")
        result = analytics.room_activity(db_path)
        assert result[0]["room_id"] == "r1"

    def test_structure(self, db_path):
        with db.get_db(db_path) as conn:
            _insert_session(conn)
        result = analytics.room_activity(db_path)
        assert all(k in result[0] for k in
                   ["room_id", "session_count", "total_duration_s", "avg_duration_s"])


# ---------------------------------------------------------------------------
# API-Endpunkte (Smoke Tests)
# ---------------------------------------------------------------------------

class TestProfileApi:
    def test_hourly_returns_24_entries(self, client):
        r = client.get("/api/profile/hourly")
        assert r.status_code == 200
        assert len(r.json()) == 24

    def test_hourly_with_room_filter(self, client):
        r = client.get("/api/profile/hourly?room_id=wohnzimmer")
        assert r.status_code == 200
        assert len(r.json()) == 24

    def test_hourly_invalid_days(self, client):
        r = client.get("/api/profile/hourly?days=0")
        assert r.status_code == 422

    def test_heatmap_returns_168_entries(self, client):
        r = client.get("/api/profile/heatmap")
        assert r.status_code == 200
        assert len(r.json()) == 168

    def test_heatmap_with_room_filter(self, client):
        r = client.get("/api/profile/heatmap?room_id=wohnzimmer")
        assert r.status_code == 200

    def test_zones_returns_list(self, client):
        r = client.get("/api/profile/zones")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_rooms_returns_list(self, client):
        r = client.get("/api/profile/rooms")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_rooms_with_data(self, client):
        """Nach Motion-Post erscheint der Raum in der Raumliste."""
        client.post("/api/simulate/motion", json={
            "sensor_id":    "radar_wohnzimmer",
            "room_id":      "wohnzimmer",
            "timestamp_ms": int(time.time() * 1000),
            "target_count": 1,
            "targets": [{
                "id": 1, "x_mm": 0.0, "y_mm": 2000.0,
                "speed_mm_s": 100.0, "distance_mm": 2000.0,
            }],
        })
        r = client.get("/api/profile/rooms")
        assert r.status_code == 200
        rooms = r.json()
        assert any(room["room_id"] == "wohnzimmer" for room in rooms)
