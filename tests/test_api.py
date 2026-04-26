"""Tests für POST /api/simulate/motion, GET /api/live und WS /ws/live."""
import sys
import time
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from fastapi.testclient import TestClient
from app.main import app
from app import database as db
from app import live_state


@pytest.fixture(autouse=True)
def clear_live_state():
    """Live-State und DB-Rate-Limiter vor jedem Test leeren."""
    live_state.clear()
    db._reset_for_tests()
    yield
    live_state.clear()
    db._reset_for_tests()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        # Lifespan hat die DB initialisiert → Tabellen leeren und State zurücksetzen
        db._clear_tables_for_tests(app.state.db_path)
        db._reset_for_tests()
        live_state.clear()
        yield c


# ---------------------------------------------------------------------------
# Hilfsdaten
# ---------------------------------------------------------------------------

VALID_PAYLOAD = {
    "sensor_id":    "radar_wohnzimmer",
    "room_id":      "wohnzimmer",
    "timestamp_ms": 1_710_000_000_000,
    "target_count": 1,
    "targets": [
        {
            "id":          1,
            "x_mm":        0.0,
            "y_mm":        2000.0,
            "speed_mm_s":  120.0,
            "distance_mm": 2000.0,
            "angle_deg":   0.0,
        }
    ],
}


# ---------------------------------------------------------------------------
# GET /api/health – darf durch M4 nicht kaputt gehen
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_still_works(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# POST /api/simulate/motion
# ---------------------------------------------------------------------------

class TestSimulateMotion:
    def test_valid_payload_returns_ok(self, client):
        r = client.post("/api/simulate/motion", json=VALID_PAYLOAD)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["targets_processed"] == 1

    def test_unknown_sensor_returns_422(self, client):
        payload = {**VALID_PAYLOAD, "sensor_id": "radar_nicht_vorhanden"}
        r = client.post("/api/simulate/motion", json=payload)
        assert r.status_code == 422
        assert "nicht_vorhanden" in r.json()["detail"]

    def test_wrong_room_id_returns_422(self, client):
        payload = {**VALID_PAYLOAD, "room_id": "falscher_raum"}
        r = client.post("/api/simulate/motion", json=payload)
        assert r.status_code == 422

    def test_coordinates_are_transformed(self, client):
        """Geradeaus-Ziel bei rotation=0 → room_x_mm == sensor.x_mm."""
        r = client.post("/api/simulate/motion", json=VALID_PAYLOAD)
        assert r.status_code == 200
        state = live_state.get("radar_wohnzimmer")
        assert state is not None
        target = state["targets"][0]
        # Sensor ist bei x=3000, rotation=0, Ziel bei x_s=0 → room_x=3000
        assert abs(target["room_x_mm"] - 3000) < 0.1
        assert abs(target["room_y_mm"] - 2000) < 0.1

    def test_floorplan_coords_computed(self, client):
        r = client.post("/api/simulate/motion", json=VALID_PAYLOAD)
        assert r.status_code == 200
        state = live_state.get("radar_wohnzimmer")
        t = state["targets"][0]
        # Wohnzimmer: 6000×4500 mm → floorplan 300×225 px, offset (10,10)
        # room (3000, 2000) → fp (10 + 3000*300/6000, 10 + 2000*225/4500)
        #                    = (10+150, 10+100) = (160, 110)
        assert abs(t["floorplan_x"] - 160.0) < 0.1
        assert abs(t["floorplan_y"] - 110.0) < 0.1

    def test_zone_detected(self, client):
        """Ziel im TV-Bereich (500..2500, 500..2000) → zone_id='tv'."""
        # Sensor bei (3000, 0), rotation=0
        # Damit target bei room(1000, 800) landet: x_s=-2000, y_s=800
        payload = {
            **VALID_PAYLOAD,
            "targets": [{
                "id": 1, "x_mm": -2000.0, "y_mm": 800.0,
                "speed_mm_s": 0, "distance_mm": 0,
            }],
        }
        r = client.post("/api/simulate/motion", json=payload)
        assert r.status_code == 200
        t = live_state.get("radar_wohnzimmer")["targets"][0]
        assert t["zone_id"] == "tv"

    def test_target_outside_room_flagged(self, client):
        """Ziel weit hinter dem Sensor → inside_room=False."""
        payload = {
            **VALID_PAYLOAD,
            "targets": [{
                "id": 1, "x_mm": 99999.0, "y_mm": 99999.0,
                "speed_mm_s": 0, "distance_mm": 0,
            }],
        }
        r = client.post("/api/simulate/motion", json=payload)
        assert r.status_code == 200
        t = live_state.get("radar_wohnzimmer")["targets"][0]
        assert t["inside_room"] is False
        assert t["zone_id"] is None

    def test_empty_targets_accepted(self, client):
        payload = {**VALID_PAYLOAD, "targets": [], "target_count": 0}
        r = client.post("/api/simulate/motion", json=payload)
        assert r.status_code == 200
        assert r.json()["targets_processed"] == 0

    def test_multiple_sensors_independent(self, client):
        """Zwei verschiedene Sensoren haben unabhängige States."""
        r1 = client.post("/api/simulate/motion", json=VALID_PAYLOAD)
        assert r1.status_code == 200

        payload2 = {
            "sensor_id":    "radar_kueche",
            "room_id":      "kueche",
            "timestamp_ms": 1_710_000_000_001,
            "target_count": 1,
            "targets": [{
                "id": 1, "x_mm": 0.0, "y_mm": 1000.0,
                "speed_mm_s": 50, "distance_mm": 1000,
            }],
        }
        r2 = client.post("/api/simulate/motion", json=payload2)
        assert r2.status_code == 200

        assert live_state.get("radar_wohnzimmer") is not None
        assert live_state.get("radar_kueche") is not None
        assert live_state.get("radar_wohnzimmer")["room_id"] == "wohnzimmer"
        assert live_state.get("radar_kueche")["room_id"] == "kueche"

    def test_negative_y_mm_rejected(self, client):
        """y_mm < 0 ist physikalisch unmöglich (Entfernung) → 422."""
        payload = {
            **VALID_PAYLOAD,
            "targets": [{"id": 1, "x_mm": 0.0, "y_mm": -100.0}],
        }
        r = client.post("/api/simulate/motion", json=payload)
        assert r.status_code == 422

    def test_missing_sensor_id_field_returns_422(self, client):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "sensor_id"}
        r = client.post("/api/simulate/motion", json=payload)
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/live
# ---------------------------------------------------------------------------

class TestGetLive:
    def test_empty_state_returns_empty_sensors(self, client):
        r = client.get("/api/live")
        assert r.status_code == 200
        body = r.json()
        assert body["sensors"] == {}
        assert body["sensor_count"] == 0
        assert "timestamp_ms" in body

    def test_live_reflects_posted_data(self, client):
        client.post("/api/simulate/motion", json=VALID_PAYLOAD)
        r = client.get("/api/live")
        assert r.status_code == 200
        sensors = r.json()["sensors"]
        assert "radar_wohnzimmer" in sensors
        s = sensors["radar_wohnzimmer"]
        assert s["room_id"] == "wohnzimmer"
        assert s["target_count"] == 1

    def test_online_flag_true_immediately_after_post(self, client):
        client.post("/api/simulate/motion", json=VALID_PAYLOAD)
        r = client.get("/api/live")
        assert r.json()["sensors"]["radar_wohnzimmer"]["online"] is True

    def test_last_seen_seconds_ago_is_small(self, client):
        client.post("/api/simulate/motion", json=VALID_PAYLOAD)
        r = client.get("/api/live")
        elapsed = r.json()["sensors"]["radar_wohnzimmer"]["last_seen_seconds_ago"]
        assert elapsed is not None
        assert elapsed < 2.0

    def test_internal_keys_not_exposed(self, client):
        client.post("/api/simulate/motion", json=VALID_PAYLOAD)
        r = client.get("/api/live")
        sensor_data = r.json()["sensors"]["radar_wohnzimmer"]
        for key in sensor_data:
            assert not key.startswith("_"), f"Interner Schlüssel '{key}' nach außen sichtbar"

    def test_sensor_count_matches(self, client):
        for sid, rid in [("radar_wohnzimmer", "wohnzimmer"),
                         ("radar_flur", "flur"),
                         ("radar_kueche", "kueche")]:
            client.post("/api/simulate/motion", json={
                **VALID_PAYLOAD,
                "sensor_id": sid, "room_id": rid,
            })
        r = client.get("/api/live")
        assert r.json()["sensor_count"] == 3

    def test_targets_contain_floorplan_coords(self, client):
        client.post("/api/simulate/motion", json=VALID_PAYLOAD)
        r = client.get("/api/live")
        t = r.json()["sensors"]["radar_wohnzimmer"]["targets"][0]
        assert "floorplan_x" in t
        assert "floorplan_y" in t
        assert "room_x_mm" in t
        assert "room_y_mm" in t
        assert "zone_id" in t
        assert "inside_room" in t


# ---------------------------------------------------------------------------
# WebSocket /ws/live
# ---------------------------------------------------------------------------

class TestWebSocket:
    def test_initial_state_sent_on_connect_empty(self, client):
        """Leerer State: erster Frame hat sensors={}."""
        with client.websocket_connect("/ws/live") as ws:
            data = ws.receive_json()
        assert data["sensors"] == {}
        assert data["sensor_count"] == 0
        assert "timestamp_ms" in data

    def test_initial_state_sent_on_connect_with_data(self, client):
        """Wenn schon Daten vorhanden: erster Frame enthält sie."""
        client.post("/api/simulate/motion", json=VALID_PAYLOAD)
        with client.websocket_connect("/ws/live") as ws:
            data = ws.receive_json()
        assert "radar_wohnzimmer" in data["sensors"]

    def test_broadcast_received_after_motion_post(self, client):
        """Nach POST /simulate/motion kommt ein Update über den WS."""
        with client.websocket_connect("/ws/live") as ws:
            # Initialen Frame empfangen
            ws.receive_json()
            # Jetzt Motion senden
            client.post("/api/simulate/motion", json=VALID_PAYLOAD)
            # Update-Frame empfangen
            update = ws.receive_json()
        assert "radar_wohnzimmer" in update["sensors"]
        assert update["sensors"]["radar_wohnzimmer"]["target_count"] == 1

    def test_broadcast_contains_transformed_coords(self, client):
        """Der WS-Broadcast enthält bereits umgerechnete Koordinaten."""
        with client.websocket_connect("/ws/live") as ws:
            ws.receive_json()
            client.post("/api/simulate/motion", json=VALID_PAYLOAD)
            update = ws.receive_json()
        t = update["sensors"]["radar_wohnzimmer"]["targets"][0]
        assert "floorplan_x" in t
        assert "room_x_mm" in t
        assert abs(t["room_x_mm"] - 3000) < 0.1

    def test_online_flag_in_broadcast(self, client):
        with client.websocket_connect("/ws/live") as ws:
            ws.receive_json()
            client.post("/api/simulate/motion", json=VALID_PAYLOAD)
            update = ws.receive_json()
        assert update["sensors"]["radar_wohnzimmer"]["online"] is True

    def test_health_includes_ws_client_count(self, client):
        """GET /api/health gibt ws_clients zurück."""
        r = client.get("/api/health")
        assert r.status_code == 200
        assert "ws_clients" in r.json()

    def test_multiple_posts_each_trigger_broadcast(self, client):
        """Zwei aufeinanderfolgende POSTs → zwei Broadcast-Frames."""
        with client.websocket_connect("/ws/live") as ws:
            ws.receive_json()  # initial
            client.post("/api/simulate/motion", json=VALID_PAYLOAD)
            frame1 = ws.receive_json()
            client.post("/api/simulate/motion", json={
                **VALID_PAYLOAD, "timestamp_ms": VALID_PAYLOAD["timestamp_ms"] + 500,
            })
            frame2 = ws.receive_json()
        assert frame1["timestamp_ms"] <= frame2["timestamp_ms"]


# ---------------------------------------------------------------------------
# GET /api/history/*
# ---------------------------------------------------------------------------

class TestHistoryApi:
    def test_positions_empty_initially(self, client):
        r = client.get("/api/history/positions")
        assert r.status_code == 200
        assert r.json() == []

    def test_sessions_empty_initially(self, client):
        r = client.get("/api/history/sessions")
        assert r.status_code == 200
        assert r.json() == []

    def test_events_empty_initially(self, client):
        r = client.get("/api/history/events")
        assert r.status_code == 200
        assert r.json() == []

    def test_positions_recorded_after_motion(self, client):
        client.post("/api/simulate/motion", json=VALID_PAYLOAD)
        r = client.get("/api/history/positions")
        assert r.status_code == 200
        assert len(r.json()) == 1
        pos = r.json()[0]
        assert pos["sensor_id"] == "radar_wohnzimmer"
        assert pos["room_id"] == "wohnzimmer"
        assert pos["zone_id"] is not None or pos["zone_id"] is None  # Feld vorhanden

    def test_session_created_after_motion(self, client):
        client.post("/api/simulate/motion", json=VALID_PAYLOAD)
        r = client.get("/api/history/sessions")
        assert r.status_code == 200
        assert len(r.json()) == 1
        s = r.json()[0]
        assert s["room_id"] == "wohnzimmer"
        assert s["ended_at_ms"] is None

    def test_session_closed_after_empty_targets(self, client):
        client.post("/api/simulate/motion", json=VALID_PAYLOAD)
        db._last_write_mono.clear()  # Rate-Limit für zweiten POST zurücksetzen
        client.post("/api/simulate/motion", json={
            **VALID_PAYLOAD,
            "targets": [], "target_count": 0,
            "timestamp_ms": VALID_PAYLOAD["timestamp_ms"] + 1000,
        })
        r = client.get("/api/history/sessions")
        assert r.status_code == 200
        s = r.json()[0]
        assert s["ended_at_ms"] is not None

    def test_positions_filter_by_sensor(self, client):
        client.post("/api/simulate/motion", json=VALID_PAYLOAD)
        r = client.get("/api/history/positions?sensor_id=radar_wohnzimmer")
        assert r.status_code == 200
        assert all(p["sensor_id"] == "radar_wohnzimmer" for p in r.json())

    def test_positions_filter_by_room(self, client):
        client.post("/api/simulate/motion", json=VALID_PAYLOAD)
        r = client.get("/api/history/positions?room_id=kueche")
        assert r.status_code == 200
        assert r.json() == []

    def test_limit_param(self, client):
        r = client.get("/api/history/positions?limit=5")
        assert r.status_code == 200

    def test_invalid_limit_rejected(self, client):
        r = client.get("/api/history/positions?limit=0")
        assert r.status_code == 422
