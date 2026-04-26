"""Tests für app/mqtt_service.py und MQTT-Integration."""
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from fastapi.testclient import TestClient
from app.main import app
from app import database as db
from app import live_state
from app.mqtt_service import MqttService


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


def _make_app_mock(tmp_path):
    """Baut ein minimales App-Mock mit State für _process-Tests."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
    from app.config import load_rooms, load_sensors, load_settings
    import asyncio

    mock = MagicMock()
    mock.state.rooms    = load_rooms()
    mock.state.sensors  = load_sensors(mock.state.rooms)
    mock.state.settings = load_settings()
    mock.state.db_path  = str(tmp_path / "test.db")
    mock.state.event_loop = asyncio.new_event_loop()

    db.init_db(mock.state.db_path)
    return mock


# ---------------------------------------------------------------------------
# MqttService – Grundstruktur
# ---------------------------------------------------------------------------

class TestMqttServiceInterface:
    def test_connected_false_initially(self):
        svc = MqttService()
        assert svc.connected is False

    def test_stop_without_start_is_safe(self):
        svc = MqttService()
        svc.stop()  # darf nicht werfen

    @patch("app.mqtt_service.mqtt.Client")
    def test_start_calls_connect_async(self, MockClient, tmp_path):
        mock_client = MagicMock()
        MockClient.return_value = mock_client

        svc = MqttService()
        app_mock = _make_app_mock(tmp_path)
        svc.start(app_mock)

        mock_client.connect_async.assert_called_once()
        mock_client.loop_start.assert_called_once()
        svc.stop()

    @patch("app.mqtt_service.mqtt.Client")
    def test_start_connect_failure_does_not_crash(self, MockClient, tmp_path):
        mock_client = MagicMock()
        mock_client.connect_async.side_effect = OSError("Broker nicht erreichbar")
        MockClient.return_value = mock_client

        svc = MqttService()
        svc.start(_make_app_mock(tmp_path))  # darf nicht werfen
        svc.stop()

    def test_on_connect_rc0_sets_connected(self):
        svc = MqttService()
        svc._topic = "test/+"
        mock_client = MagicMock()
        svc._on_connect(mock_client, None, {}, 0)
        assert svc.connected is True
        mock_client.subscribe.assert_called_once_with("test/+")

    def test_on_connect_rc_nonzero_stays_disconnected(self):
        svc = MqttService()
        svc._on_connect(MagicMock(), None, {}, 1)
        assert svc.connected is False

    def test_on_disconnect_clears_connected(self):
        svc = MqttService()
        svc._connected = True
        svc._on_disconnect(MagicMock(), None, 1)
        assert svc.connected is False


# ---------------------------------------------------------------------------
# MqttService._process – Payload-Verarbeitung
# ---------------------------------------------------------------------------

class TestMqttProcess:
    PAYLOAD = {
        "sensor_id":    "radar_wohnzimmer",
        "room_id":      "wohnzimmer",
        "timestamp_ms": 1_710_000_000_000,
        "target_count": 1,
        "targets": [{"id": 1, "x_mm": 0.0, "y_mm": 2000.0,
                     "speed_mm_s": 100.0, "distance_mm": 2000.0}],
    }

    @pytest.fixture()
    def svc(self, tmp_path):
        s = MqttService()
        s._app = _make_app_mock(tmp_path)
        return s

    def test_valid_payload_updates_live_state(self, svc):
        svc._process(self.PAYLOAD)
        state = live_state.get("radar_wohnzimmer")
        assert state is not None
        assert state["room_id"] == "wohnzimmer"
        assert state["target_count"] == 1

    def test_coordinates_transformed(self, svc):
        svc._process(self.PAYLOAD)
        t = live_state.get("radar_wohnzimmer")["targets"][0]
        # Sensor bei x=3000, rotation=0, Ziel y_s=2000 → room_y=2000
        assert abs(t["room_y_mm"] - 2000) < 0.1
        assert "floorplan_x" in t

    def test_unknown_sensor_ignored(self, svc):
        payload = {**self.PAYLOAD, "sensor_id": "radar_unbekannt"}
        svc._process(payload)
        assert live_state.get("radar_unbekannt") is None

    def test_wrong_room_id_ignored(self, svc):
        payload = {**self.PAYLOAD, "room_id": "falscher_raum"}
        svc._process(payload)
        assert live_state.get("radar_wohnzimmer") is None

    def test_negative_y_mm_filtered(self, svc):
        payload = {**self.PAYLOAD, "targets": [
            {"id": 1, "x_mm": 0.0, "y_mm": -100.0}
        ]}
        svc._process(payload)
        state = live_state.get("radar_wohnzimmer")
        assert state is not None
        assert state["target_count"] == 0

    def test_missing_fields_handled_gracefully(self, svc):
        svc._process({"sensor_id": "radar_wohnzimmer"})  # room_id fehlt
        assert live_state.get("radar_wohnzimmer") is None

    def test_db_record_written(self, svc):
        svc._process(self.PAYLOAD)
        rows = db.query_positions(svc._app.state.db_path)
        assert len(rows) == 1

    def test_empty_targets_closes_session(self, svc):
        svc._process(self.PAYLOAD)                      # Session öffnen
        db._last_write_mono.clear()
        svc._process({**self.PAYLOAD,                   # Session schließen
                      "targets": [], "target_count": 0,
                      "timestamp_ms": self.PAYLOAD["timestamp_ms"] + 1000})
        sessions = db.query_sessions(svc._app.state.db_path)
        assert sessions[0]["ended_at_ms"] is not None


# ---------------------------------------------------------------------------
# GET /api/health – mqtt_connected
# ---------------------------------------------------------------------------

class TestHealthMqtt:
    def test_health_returns_mqtt_connected_field(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert "mqtt_connected" in r.json()

    def test_mqtt_connected_is_bool(self, client):
        r = client.get("/api/health")
        assert isinstance(r.json()["mqtt_connected"], bool)

    def test_mqtt_connected_false_without_broker(self, client):
        # Kein echter Broker → mqtt_connected muss False sein
        r = client.get("/api/health")
        assert r.json()["mqtt_connected"] is False
