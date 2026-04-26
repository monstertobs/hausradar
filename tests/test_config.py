"""Tests für server/app/config.py – Konfigurationsvalidierung."""
import json
import sys
import os
import pytest
from pathlib import Path

# server/ ins sys.path aufnehmen
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from app.config import load_rooms, load_sensors, load_settings, CONFIG_DIR


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, filename: str, data) -> Path:
    p = tmp_path / filename
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _patch_config(monkeypatch, tmp_path: Path):
    """Lässt config.py aus tmp_path statt aus config/ lesen."""
    import app.config as cfg
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path)


def _minimal_room(
    rid="raum1", name="Raum 1",
    w=5000, h=4000,
    fp=None, zones=None,
):
    return {
        "id": rid, "name": name,
        "width_mm": w, "height_mm": h,
        "floorplan": fp or {"x": 0, "y": 0, "width": 250, "height": 200},
        "zones": zones or [],
    }


def _minimal_sensor(sid="s1", name="Sensor 1", room_id="raum1",
                    x=2500, y=2000):
    return {
        "id": sid, "name": name, "room_id": room_id,
        "x_mm": x, "y_mm": y,
        "mount_height_mm": 2200,
        "rotation_deg": 0,
        "enabled": True,
    }


def _minimal_settings():
    return {
        "mqtt": {
            "host": "localhost", "port": 1883,
            "topic": "hausradar/sensor/+/state",
            "reconnect_delay_seconds": 5,
        },
        "database": {
            "path": "data/hausradar.db",
            "retention_days": 30,
            "max_writes_per_second_per_sensor": 2,
        },
        "websocket": {"broadcast_interval_ms": 100},
        "live": {
            "sensor_offline_timeout_seconds": 15,
            "recent_activity_timeout_seconds": 30,
        },
        "server": {"host": "0.0.0.0", "port": 8000},
    }


# ---------------------------------------------------------------------------
# load_rooms
# ---------------------------------------------------------------------------

class TestLoadRooms:
    def test_valid_rooms_loaded(self, monkeypatch, tmp_path):
        _write(tmp_path, "rooms.json", [_minimal_room()])
        _patch_config(monkeypatch, tmp_path)
        rooms = load_rooms()
        assert len(rooms) == 1
        assert rooms[0]["id"] == "raum1"

    def test_file_not_found(self, monkeypatch, tmp_path):
        _patch_config(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError, match="nicht gefunden"):
            load_rooms()

    def test_invalid_json(self, monkeypatch, tmp_path):
        (tmp_path / "rooms.json").write_text("{ ungültig json }", encoding="utf-8")
        _patch_config(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError, match="Ungültiges JSON"):
            load_rooms()

    def test_missing_id(self, monkeypatch, tmp_path):
        room = _minimal_room()
        del room["id"]
        _write(tmp_path, "rooms.json", [room])
        _patch_config(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError, match="'id' fehlt"):
            load_rooms()

    def test_negative_width(self, monkeypatch, tmp_path):
        _write(tmp_path, "rooms.json", [_minimal_room(w=-100)])
        _patch_config(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError, match="width_mm"):
            load_rooms()

    def test_zero_height(self, monkeypatch, tmp_path):
        _write(tmp_path, "rooms.json", [_minimal_room(h=0)])
        _patch_config(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError, match="height_mm"):
            load_rooms()

    def test_duplicate_room_ids(self, monkeypatch, tmp_path):
        _write(tmp_path, "rooms.json", [_minimal_room("r1"), _minimal_room("r1")])
        _patch_config(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError, match="doppelt"):
            load_rooms()

    def test_empty_list_rejected(self, monkeypatch, tmp_path):
        _write(tmp_path, "rooms.json", [])
        _patch_config(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError, match="Mindestens ein Raum"):
            load_rooms()

    def test_zone_outside_room_logs_warning(self, monkeypatch, tmp_path, caplog):
        import logging
        zone = {"id": "z1", "name": "Zone 1",
                "x_mm": 4000, "y_mm": 0, "width_mm": 2000, "height_mm": 1000}
        _write(tmp_path, "rooms.json", [_minimal_room(zones=[zone])])
        _patch_config(monkeypatch, tmp_path)
        with caplog.at_level(logging.WARNING):
            load_rooms()
        assert any("Raumgrenzen" in r.message for r in caplog.records)

    def test_duplicate_zone_ids_in_same_room(self, monkeypatch, tmp_path):
        z = {"id": "z1", "name": "Zone", "x_mm": 0, "y_mm": 0,
             "width_mm": 100, "height_mm": 100}
        _write(tmp_path, "rooms.json", [_minimal_room(zones=[z, z.copy()])])
        _patch_config(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError, match="doppelt"):
            load_rooms()

    def test_floorplan_missing_key(self, monkeypatch, tmp_path):
        fp = {"x": 0, "y": 0, "width": 100}  # height fehlt
        _write(tmp_path, "rooms.json", [_minimal_room(fp=fp)])
        _patch_config(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError, match="height"):
            load_rooms()

    def test_error_message_lists_all_problems(self, monkeypatch, tmp_path):
        r1 = _minimal_room(w=0)   # width_mm fehlerh
        r2 = _minimal_room("r2", h=0)  # height_mm fehlerhaft
        _write(tmp_path, "rooms.json", [r1, r2])
        _patch_config(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError) as exc_info:
            load_rooms()
        msg = str(exc_info.value)
        assert "width_mm" in msg
        assert "height_mm" in msg

    def test_real_rooms_json_is_valid(self):
        """Die echte rooms.json im Projekt muss fehlerfrei laden."""
        rooms = load_rooms()
        assert len(rooms) == 5
        ids = {r["id"] for r in rooms}
        assert "wohnzimmer" in ids
        assert "keller" in ids


# ---------------------------------------------------------------------------
# load_sensors
# ---------------------------------------------------------------------------

class TestLoadSensors:
    def _setup(self, monkeypatch, tmp_path, rooms=None, sensors=None):
        if rooms is None:
            rooms = [_minimal_room()]
        if sensors is None:
            sensors = [_minimal_sensor()]
        _write(tmp_path, "rooms.json", rooms)
        _write(tmp_path, "sensors.json", sensors)
        _patch_config(monkeypatch, tmp_path)

    def test_valid_sensor_loaded(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path)
        rooms = load_rooms()
        sensors = load_sensors(rooms)
        assert len(sensors) == 1
        assert sensors[0]["id"] == "s1"

    def test_unknown_room_id(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path,
                    sensors=[_minimal_sensor(room_id="nicht_vorhanden")])
        rooms = load_rooms()
        with pytest.raises(RuntimeError, match="nicht_vorhanden"):
            load_sensors(rooms)

    def test_error_lists_known_rooms(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path,
                    sensors=[_minimal_sensor(room_id="falsch")])
        rooms = load_rooms()
        with pytest.raises(RuntimeError) as exc_info:
            load_sensors(rooms)
        assert "raum1" in str(exc_info.value)

    def test_missing_sensor_id(self, monkeypatch, tmp_path):
        s = _minimal_sensor()
        del s["id"]
        self._setup(monkeypatch, tmp_path, sensors=[s])
        rooms = load_rooms()
        with pytest.raises(RuntimeError, match="'id' fehlt"):
            load_sensors(rooms)

    def test_missing_room_id_field(self, monkeypatch, tmp_path):
        s = _minimal_sensor()
        del s["room_id"]
        self._setup(monkeypatch, tmp_path, sensors=[s])
        rooms = load_rooms()
        with pytest.raises(RuntimeError, match="room_id"):
            load_sensors(rooms)

    def test_duplicate_sensor_ids(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path,
                    sensors=[_minimal_sensor("s1"), _minimal_sensor("s1")])
        rooms = load_rooms()
        with pytest.raises(RuntimeError, match="doppelt"):
            load_sensors(rooms)

    def test_sensor_outside_room_logs_warning(self, monkeypatch, tmp_path, caplog):
        import logging
        # x_mm weit außerhalb
        self._setup(monkeypatch, tmp_path,
                    sensors=[_minimal_sensor(x=99999, y=99999)])
        rooms = load_rooms()
        with caplog.at_level(logging.WARNING):
            load_sensors(rooms)
        assert any("außerhalb" in r.message for r in caplog.records)

    def test_sensor_at_wall_y0_is_valid(self, monkeypatch, tmp_path, caplog):
        import logging
        # y_mm=0 ist Wandmontage – kein Fehler, keine Warnung
        self._setup(monkeypatch, tmp_path,
                    sensors=[_minimal_sensor(x=2500, y=0)])
        rooms = load_rooms()
        with caplog.at_level(logging.WARNING):
            load_sensors(rooms)
        outside_warnings = [r for r in caplog.records
                            if "außerhalb" in r.message]
        assert len(outside_warnings) == 0

    def test_invalid_enabled_field(self, monkeypatch, tmp_path):
        s = _minimal_sensor()
        s["enabled"] = "ja"  # muss bool sein
        self._setup(monkeypatch, tmp_path, sensors=[s])
        rooms = load_rooms()
        with pytest.raises(RuntimeError, match="enabled"):
            load_sensors(rooms)

    def test_real_sensors_json_is_valid(self):
        """Die echte sensors.json im Projekt muss fehlerfrei laden."""
        rooms = load_rooms()
        sensors = load_sensors(rooms)
        assert len(sensors) == 5
        ids = {s["id"] for s in sensors}
        assert "radar_wohnzimmer" in ids


# ---------------------------------------------------------------------------
# load_settings
# ---------------------------------------------------------------------------

class TestLoadSettings:
    def test_real_settings_json_is_valid(self):
        settings = load_settings()
        assert settings["mqtt"]["host"] == "localhost"
        assert settings["server"]["port"] == 8000

    def test_valid_custom_settings(self, monkeypatch, tmp_path):
        _write(tmp_path, "settings.json", _minimal_settings())
        _patch_config(monkeypatch, tmp_path)
        s = load_settings()
        assert s["mqtt"]["port"] == 1883

    def test_missing_mqtt_section(self, monkeypatch, tmp_path):
        data = _minimal_settings()
        del data["mqtt"]
        _write(tmp_path, "settings.json", data)
        _patch_config(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError, match="mqtt"):
            load_settings()

    def test_invalid_mqtt_port(self, monkeypatch, tmp_path):
        data = _minimal_settings()
        data["mqtt"]["port"] = 99999
        _write(tmp_path, "settings.json", data)
        _patch_config(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError, match="mqtt.port"):
            load_settings()

    def test_mqtt_port_must_be_int(self, monkeypatch, tmp_path):
        data = _minimal_settings()
        data["mqtt"]["port"] = "1883"
        _write(tmp_path, "settings.json", data)
        _patch_config(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError, match="mqtt.port"):
            load_settings()

    def test_missing_database_section(self, monkeypatch, tmp_path):
        data = _minimal_settings()
        del data["database"]
        _write(tmp_path, "settings.json", data)
        _patch_config(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError, match="database"):
            load_settings()

    def test_invalid_retention_days(self, monkeypatch, tmp_path):
        data = _minimal_settings()
        data["database"]["retention_days"] = 0
        _write(tmp_path, "settings.json", data)
        _patch_config(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError, match="retention_days"):
            load_settings()

    def test_error_collects_multiple_problems(self, monkeypatch, tmp_path):
        data = _minimal_settings()
        data["mqtt"]["host"] = ""
        data["server"]["port"] = 0
        _write(tmp_path, "settings.json", data)
        _patch_config(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError) as exc_info:
            load_settings()
        msg = str(exc_info.value)
        assert "mqtt.host" in msg
        assert "server.port" in msg
