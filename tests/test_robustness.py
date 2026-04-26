"""Tests für M15-Robustheit: WAL-Mode, Payload-Validierung, Health, Zombie-Sessions."""
import sys
import time
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from fastapi.testclient import TestClient
from app.main import app
from app import database as db
from app import live_state


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_state():
    live_state.clear()
    db._reset_for_tests()
    yield
    live_state.clear()
    db._reset_for_tests()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        db._clear_tables_for_tests(app.state.db_path)
        db._reset_for_tests()
        live_state.clear()
        yield c


BASE_PAYLOAD = {
    "sensor_id":    "radar_wohnzimmer",
    "room_id":      "wohnzimmer",
    "timestamp_ms": 1_710_000_000_000,
    "target_count": 1,
    "targets": [{"id": 1, "x_mm": 0.0, "y_mm": 2000.0,
                 "speed_mm_s": 100.0, "distance_mm": 2000.0}],
}


# ---------------------------------------------------------------------------
# SQLite WAL-Mode
# ---------------------------------------------------------------------------

class TestWalMode:
    def test_wal_mode_enabled(self, tmp_path):
        path = str(tmp_path / "test.db")
        db.init_db(path)
        with db.get_db(path) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_wal_mode_idempotent(self, tmp_path):
        """init_db kann mehrfach aufgerufen werden ohne WAL zu verlieren."""
        path = str(tmp_path / "test.db")
        db.init_db(path)
        db.init_db(path)
        with db.get_db(path) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"


# ---------------------------------------------------------------------------
# Zombie-Sessions beim Start schließen
# ---------------------------------------------------------------------------

class TestZombieSessions:
    def test_open_sessions_closed_on_init(self, tmp_path):
        path = str(tmp_path / "test.db")
        db.init_db(path)

        # Session ohne Ende direkt in DB schreiben (simuliert Absturz)
        with db.get_db(path) as conn:
            conn.execute(
                "INSERT INTO motion_sessions (room_id, started_at_ms, max_targets)"
                " VALUES ('wohnzimmer', 1000, 1)"
            )

        # Erneuter Start → Session muss geschlossen werden
        db.init_db(path)

        sessions = db.query_sessions(path)
        assert len(sessions) == 1
        assert sessions[0]["ended_at_ms"] is not None

    def test_already_closed_sessions_untouched(self, tmp_path):
        path = str(tmp_path / "test.db")
        db.init_db(path)

        with db.get_db(path) as conn:
            conn.execute(
                "INSERT INTO motion_sessions"
                " (room_id, started_at_ms, ended_at_ms, max_targets)"
                " VALUES ('wohnzimmer', 1000, 2000, 1)"
            )

        db.init_db(path)
        sessions = db.query_sessions(path)
        assert sessions[0]["ended_at_ms"] == 2000  # unveränderter Wert


# ---------------------------------------------------------------------------
# DB-Health-Check
# ---------------------------------------------------------------------------

class TestCheckDb:
    def test_check_db_returns_true_for_valid_db(self, tmp_path):
        path = str(tmp_path / "test.db")
        db.init_db(path)
        assert db.check_db(path) is True

    def test_check_db_returns_false_for_missing_db(self):
        # Nicht-existierende DB → SQLite erstellt leere Datei, PRAGMA SELECT 1 OK
        # Stattdessen: schreibgeschütztes Verzeichnis simulieren mit ungültigem Pfad
        assert db.check_db("/dev/null/nonexistent.db") is False


# ---------------------------------------------------------------------------
# MotionPayload: target_count vs. len(targets)
# ---------------------------------------------------------------------------

class TestTargetCountValidation:
    def test_matching_count_accepted(self, client):
        r = client.post("/api/simulate/motion", json=BASE_PAYLOAD)
        assert r.status_code == 200

    def test_count_too_high_rejected(self, client):
        payload = {**BASE_PAYLOAD, "target_count": 2}  # 1 Target in Liste
        r = client.post("/api/simulate/motion", json=payload)
        assert r.status_code == 422

    def test_count_too_low_rejected(self, client):
        payload = {**BASE_PAYLOAD, "target_count": 0}  # 1 Target in Liste
        r = client.post("/api/simulate/motion", json=payload)
        assert r.status_code == 422

    def test_zero_count_empty_list_accepted(self, client):
        payload = {**BASE_PAYLOAD, "target_count": 0, "targets": []}
        r = client.post("/api/simulate/motion", json=payload)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# MotionPayload: timestamp_ms
# ---------------------------------------------------------------------------

class TestTimestampValidation:
    def test_valid_timestamp_accepted(self, client):
        r = client.post("/api/simulate/motion", json=BASE_PAYLOAD)
        assert r.status_code == 200

    def test_zero_timestamp_rejected(self, client):
        payload = {**BASE_PAYLOAD, "timestamp_ms": 0}
        r = client.post("/api/simulate/motion", json=payload)
        assert r.status_code == 422

    def test_negative_timestamp_rejected(self, client):
        payload = {**BASE_PAYLOAD, "timestamp_ms": -1}
        r = client.post("/api/simulate/motion", json=payload)
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Health-Endpoint: uptime_s und db_ok
# ---------------------------------------------------------------------------

class TestHealthRobustness:
    def test_health_has_uptime_s(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert "uptime_s" in r.json()

    def test_uptime_s_is_nonneg_float(self, client):
        r = client.get("/api/health")
        assert isinstance(r.json()["uptime_s"], (int, float))
        assert r.json()["uptime_s"] >= 0

    def test_health_has_db_ok(self, client):
        r = client.get("/api/health")
        assert "db_ok" in r.json()

    def test_db_ok_is_true_normally(self, client):
        r = client.get("/api/health")
        assert r.json()["db_ok"] is True
