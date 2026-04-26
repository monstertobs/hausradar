"""Tests für server/app/database.py."""
import sys
import time
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from app import database as db


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


def _targets(count=1, inside=True):
    return [
        {
            "id": i + 1,
            "inside_room": inside,
            "room_x_mm":   float(i * 100),
            "room_y_mm":   float(i * 50),
            "zone_id":     "tv" if inside else None,
            "speed_mm_s":  100.0,
            "distance_mm": 500.0,
        }
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

class TestInitDb:
    def test_creates_all_tables(self, db_path):
        with db.get_db(db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "target_positions" in tables
        assert "motion_sessions"  in tables
        assert "sensor_events"    in tables

    def test_creates_parent_directory(self, tmp_path):
        path = str(tmp_path / "subdir" / "deeper" / "test.db")
        db.init_db(path)
        assert Path(path).exists()

    def test_idempotent(self, db_path):
        db.init_db(db_path)  # zweites Mal darf nicht scheitern


# ---------------------------------------------------------------------------
# record_motion – Positionsspeicherung
# ---------------------------------------------------------------------------

class TestRecordMotionPositions:
    def test_inserts_inside_room_target(self, db_path):
        db.record_motion(db_path, "s1", "r1", 1000, _targets(), float("inf"))
        rows = db.query_positions(db_path)
        assert len(rows) == 1
        assert rows[0]["sensor_id"]  == "s1"
        assert rows[0]["room_id"]    == "r1"
        assert rows[0]["zone_id"]    == "tv"
        assert rows[0]["room_x_mm"]  == 0.0

    def test_skips_outside_room_target(self, db_path):
        db.record_motion(db_path, "s1", "r1", 1000, _targets(inside=False), float("inf"))
        assert db.query_positions(db_path) == []

    def test_multiple_targets_per_call(self, db_path):
        db.record_motion(db_path, "s1", "r1", 1000, _targets(3), float("inf"))
        assert len(db.query_positions(db_path)) == 3

    def test_empty_targets_list(self, db_path):
        db.record_motion(db_path, "s1", "r1", 1000, [], float("inf"))
        assert db.query_positions(db_path) == []


# ---------------------------------------------------------------------------
# record_motion – Rate-Limiting
# ---------------------------------------------------------------------------

class TestRateLimit:
    def test_first_call_always_writes(self, db_path):
        db.record_motion(db_path, "s1", "r1", 1000, _targets(), max_writes_per_second=1)
        assert len(db.query_positions(db_path)) == 1

    def test_rapid_calls_rate_limited(self, db_path):
        for i in range(10):
            db.record_motion(db_path, "s1", "r1", 1000 + i * 10, _targets(), max_writes_per_second=1)
        # Maximal 1 Write innerhalb der ~0ms dieser Schleife
        assert len(db.query_positions(db_path)) == 1

    def test_rate_limit_per_sensor(self, db_path):
        for sid in ["s1", "s2", "s3"]:
            db.record_motion(db_path, sid, "r1", 1000, _targets(), max_writes_per_second=1)
        assert len(db.query_positions(db_path)) == 3

    def test_no_rate_limit_with_inf(self, db_path):
        for i in range(5):
            db.record_motion(db_path, "s1", "r1", 1000 + i, _targets(), float("inf"))
        assert len(db.query_positions(db_path)) == 5


# ---------------------------------------------------------------------------
# record_motion – Session-Verwaltung
# ---------------------------------------------------------------------------

class TestSessions:
    def test_session_started_on_first_target(self, db_path):
        db.record_motion(db_path, "s1", "r1", 1000, _targets(), float("inf"))
        sessions = db.query_sessions(db_path)
        assert len(sessions) == 1
        assert sessions[0]["room_id"]      == "r1"
        assert sessions[0]["started_at_ms"] == 1000
        assert sessions[0]["ended_at_ms"]  is None

    def test_session_ended_on_empty_targets(self, db_path):
        db.record_motion(db_path, "s1", "r1", 1000, _targets(), float("inf"))
        db.record_motion(db_path, "s1", "r1", 2000, [],          float("inf"))
        sessions = db.query_sessions(db_path)
        assert sessions[0]["ended_at_ms"] == 2000

    def test_max_targets_updated(self, db_path):
        db.record_motion(db_path, "s1", "r1", 1000, _targets(1), float("inf"))
        db.record_motion(db_path, "s1", "r1", 1100, _targets(3), float("inf"))
        sessions = db.query_sessions(db_path)
        assert sessions[0]["max_targets"] == 3

    def test_max_targets_not_decreased(self, db_path):
        db.record_motion(db_path, "s1", "r1", 1000, _targets(3), float("inf"))
        db.record_motion(db_path, "s1", "r1", 1100, _targets(1), float("inf"))
        assert db.query_sessions(db_path)[0]["max_targets"] == 3

    def test_new_session_after_end(self, db_path):
        db.record_motion(db_path, "s1", "r1", 1000, _targets(), float("inf"))
        db.record_motion(db_path, "s1", "r1", 2000, [],          float("inf"))
        db.record_motion(db_path, "s1", "r1", 3000, _targets(), float("inf"))
        assert len(db.query_sessions(db_path)) == 2

    def test_sessions_per_room_independent(self, db_path):
        db.record_motion(db_path, "s1", "r1", 1000, _targets(), float("inf"))
        db.record_motion(db_path, "s2", "r2", 1000, _targets(), float("inf"))
        r1_sessions = db.query_sessions(db_path, room_id="r1")
        r2_sessions = db.query_sessions(db_path, room_id="r2")
        assert len(r1_sessions) == 1
        assert len(r2_sessions) == 1


# ---------------------------------------------------------------------------
# cleanup_old_data
# ---------------------------------------------------------------------------

class TestCleanup:
    def _old_ms(self, days=40):
        return int((time.time() - days * 86400) * 1000)

    def test_deletes_old_positions(self, db_path):
        targets = _targets()
        # Manuelle Einfügung mit altem Timestamp
        with db.get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO target_positions"
                " (sensor_id, room_id, target_id, timestamp_ms, room_x_mm, room_y_mm)"
                " VALUES (?,?,?,?,?,?)",
                ("s1", "r1", 1, self._old_ms(), 0, 0),
            )
        deleted = db.cleanup_old_data(db_path, retention_days=30)
        assert deleted >= 1
        assert db.query_positions(db_path) == []

    def test_keeps_recent_positions(self, db_path):
        db.record_motion(db_path, "s1", "r1", int(time.time() * 1000), _targets(), float("inf"))
        db.cleanup_old_data(db_path, retention_days=30)
        assert len(db.query_positions(db_path)) == 1

    def test_deletes_old_closed_sessions(self, db_path):
        with db.get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO motion_sessions (room_id, started_at_ms, ended_at_ms)"
                " VALUES (?,?,?)",
                ("r1", self._old_ms(), self._old_ms() + 1000),
            )
        deleted = db.cleanup_old_data(db_path, retention_days=30)
        assert deleted >= 1

    def test_keeps_open_sessions(self, db_path):
        with db.get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO motion_sessions (room_id, started_at_ms) VALUES (?,?)",
                ("r1", self._old_ms()),
            )
        db.cleanup_old_data(db_path, retention_days=30)
        assert len(db.query_sessions(db_path)) == 1

    def test_deletes_old_sensor_events(self, db_path):
        db.record_sensor_event(db_path, "s1", "online", self._old_ms())
        deleted = db.cleanup_old_data(db_path, retention_days=30)
        assert deleted >= 1


# ---------------------------------------------------------------------------
# query_positions – Filter
# ---------------------------------------------------------------------------

class TestQueryPositions:
    @pytest.fixture(autouse=True)
    def seed(self, db_path):
        self.path = db_path
        db.record_motion(db_path, "s1", "r1", 1000, _targets(), float("inf"))
        db._reset_for_tests()
        db.record_motion(db_path, "s2", "r2", 2000, _targets(), float("inf"))
        db._reset_for_tests()
        db.record_motion(db_path, "s1", "r1", 3000, _targets(), float("inf"))

    def test_no_filter_returns_all(self):
        assert len(db.query_positions(self.path)) == 3

    def test_filter_sensor(self):
        rows = db.query_positions(self.path, sensor_id="s1")
        assert len(rows) == 2
        assert all(r["sensor_id"] == "s1" for r in rows)

    def test_filter_room(self):
        rows = db.query_positions(self.path, room_id="r2")
        assert len(rows) == 1
        assert rows[0]["sensor_id"] == "s2"

    def test_filter_from_ms(self):
        rows = db.query_positions(self.path, from_ms=1500)
        assert len(rows) == 2

    def test_filter_to_ms(self):
        rows = db.query_positions(self.path, to_ms=2500)
        assert len(rows) == 2

    def test_filter_time_range(self):
        rows = db.query_positions(self.path, from_ms=1500, to_ms=2500)
        assert len(rows) == 1
        assert rows[0]["timestamp_ms"] == 2000

    def test_limit(self):
        rows = db.query_positions(self.path, limit=1)
        assert len(rows) == 1

    def test_ordered_newest_first(self):
        rows = db.query_positions(self.path)
        assert rows[0]["timestamp_ms"] >= rows[-1]["timestamp_ms"]


# ---------------------------------------------------------------------------
# query_sessions – Filter
# ---------------------------------------------------------------------------

class TestQuerySessions:
    @pytest.fixture(autouse=True)
    def seed(self, db_path):
        self.path = db_path
        db.record_motion(db_path, "s1", "r1", 1000, _targets(), float("inf"))
        db.record_motion(db_path, "s1", "r1", 1500, [],          float("inf"))
        db._reset_for_tests()
        db.record_motion(db_path, "s2", "r2", 3000, _targets(), float("inf"))

    def test_filter_room(self):
        assert len(db.query_sessions(self.path, room_id="r1")) == 1

    def test_filter_from_ms(self):
        rows = db.query_sessions(self.path, from_ms=2000)
        assert len(rows) == 1
        assert rows[0]["room_id"] == "r2"

    def test_filter_to_ms(self):
        rows = db.query_sessions(self.path, to_ms=2000)
        assert len(rows) == 1
        assert rows[0]["room_id"] == "r1"


# ---------------------------------------------------------------------------
# record_sensor_event / query_sensor_events
# ---------------------------------------------------------------------------

class TestSensorEvents:
    def test_record_and_query(self, db_path):
        db.record_sensor_event(db_path, "s1", "online",  1000)
        db.record_sensor_event(db_path, "s1", "offline", 2000)
        rows = db.query_sensor_events(db_path, sensor_id="s1")
        assert len(rows) == 2
        assert rows[0]["event_type"] == "offline"  # neueste zuerst
        assert rows[1]["event_type"] == "online"

    def test_filter_sensor(self, db_path):
        db.record_sensor_event(db_path, "s1", "online", 1000)
        db.record_sensor_event(db_path, "s2", "online", 1000)
        assert len(db.query_sensor_events(db_path, sensor_id="s1")) == 1

    def test_filter_time_range(self, db_path):
        db.record_sensor_event(db_path, "s1", "online",  1000)
        db.record_sensor_event(db_path, "s1", "offline", 5000)
        rows = db.query_sensor_events(db_path, from_ms=2000, to_ms=6000)
        assert len(rows) == 1
        assert rows[0]["timestamp_ms"] == 5000
