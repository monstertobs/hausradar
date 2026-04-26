import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"


# ---------------------------------------------------------------------------
# JSON-Laden
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise RuntimeError(
            f"Konfigurationsdatei nicht gefunden: {path}\n"
            f"  → Tipp: Beispieldatei liegt unter {path.stem}.example.json"
        )
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Ungültiges JSON in {path} (Zeile {e.lineno}, Spalte {e.colno}):\n"
            f"  {e.msg}"
        )


# ---------------------------------------------------------------------------
# Hilfsprüfungen
# ---------------------------------------------------------------------------

def _require(errors: list, condition: bool, msg: str) -> None:
    if not condition:
        errors.append(msg)


def _is_positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and value > 0


def _is_nonneg_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and value >= 0


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


# ---------------------------------------------------------------------------
# Räume validieren
# ---------------------------------------------------------------------------

def _validate_zone(zone: Any, room_id: str, zone_index: int,
                   room_w: int, room_h: int, errors: list, warnings: list) -> Optional[str]:
    """Prüft eine Zone; gibt die zone-id zurück oder None bei Fehler."""
    prefix = f"Raum '{room_id}', Zone[{zone_index}]"
    if not isinstance(zone, dict):
        errors.append(f"{prefix}: muss ein JSON-Objekt sein")
        return None

    zid = zone.get("id")
    _require(errors, _is_nonempty_str(zid),
             f"{prefix}: 'id' fehlt oder ist leer")
    _require(errors, _is_nonempty_str(zone.get("name")),
             f"{prefix}: 'name' fehlt oder ist leer")
    _require(errors, _is_positive_number(zone.get("width_mm")),
             f"{prefix} (id='{zid}'): 'width_mm' muss eine positive Zahl sein")
    _require(errors, _is_positive_number(zone.get("height_mm")),
             f"{prefix} (id='{zid}'): 'height_mm' muss eine positive Zahl sein")
    _require(errors, _is_nonneg_number(zone.get("x_mm")),
             f"{prefix} (id='{zid}'): 'x_mm' fehlt oder ist negativ")
    _require(errors, _is_nonneg_number(zone.get("y_mm")),
             f"{prefix} (id='{zid}'): 'y_mm' fehlt oder ist negativ")

    # Zone außerhalb des Raums? → Warnung
    if (isinstance(zone.get("x_mm"), (int, float)) and
            isinstance(zone.get("width_mm"), (int, float)) and
            isinstance(zone.get("y_mm"), (int, float)) and
            isinstance(zone.get("height_mm"), (int, float))):
        z_right  = zone["x_mm"] + zone["width_mm"]
        z_bottom = zone["y_mm"] + zone["height_mm"]
        if z_right > room_w or z_bottom > room_h:
            warnings.append(
                f"Raum '{room_id}', Zone '{zid}': "
                f"ragt über Raumgrenzen hinaus "
                f"(Raum {room_w}×{room_h} mm, Zone endet bei {z_right}×{z_bottom} mm)"
            )

    return zid if _is_nonempty_str(zid) else None


def _validate_floorplan(fp: Any, room_id: str, errors: list) -> None:
    prefix = f"Raum '{room_id}', floorplan"
    if not isinstance(fp, dict):
        errors.append(f"{prefix}: muss ein JSON-Objekt sein")
        return
    for key in ("x", "y", "width", "height"):
        _require(errors, _is_nonneg_number(fp.get(key)),
                 f"{prefix}: '{key}' fehlt oder ist keine nicht-negative Zahl")


def load_rooms() -> list:
    rooms = _load_json(CONFIG_DIR / "rooms.json")

    if not isinstance(rooms, list):
        raise RuntimeError("rooms.json: Inhalt muss eine JSON-Liste sein")
    if len(rooms) == 0:
        raise RuntimeError("rooms.json: Mindestens ein Raum muss konfiguriert sein")

    errors: list = []
    warnings: list = []
    seen_ids: set = set()

    for i, room in enumerate(rooms):
        if not isinstance(room, dict):
            errors.append(f"Raum[{i}]: muss ein JSON-Objekt sein")
            continue

        rid = room.get("id")
        _require(errors, _is_nonempty_str(rid),
                 f"Raum[{i}]: 'id' fehlt oder ist leer")
        _require(errors, _is_nonempty_str(room.get("name")),
                 f"Raum '{rid}': 'name' fehlt oder ist leer")
        _require(errors, _is_positive_number(room.get("width_mm")),
                 f"Raum '{rid}': 'width_mm' muss eine positive Zahl sein")
        _require(errors, _is_positive_number(room.get("height_mm")),
                 f"Raum '{rid}': 'height_mm' muss eine positive Zahl sein")

        if rid and rid in seen_ids:
            errors.append(f"Raum-ID '{rid}' ist doppelt vorhanden")
        elif rid:
            seen_ids.add(rid)

        _validate_floorplan(room.get("floorplan"), rid or f"[{i}]", errors)

        zones = room.get("zones", [])
        if not isinstance(zones, list):
            errors.append(f"Raum '{rid}': 'zones' muss eine Liste sein")
        else:
            zone_ids: set = set()
            room_w = room.get("width_mm", 0)
            room_h = room.get("height_mm", 0)
            for j, zone in enumerate(zones):
                zid = _validate_zone(zone, rid or f"[{i}]", j,
                                     room_w, room_h, errors, warnings)
                if zid:
                    if zid in zone_ids:
                        errors.append(
                            f"Raum '{rid}': Zonen-ID '{zid}' ist doppelt vorhanden"
                        )
                    else:
                        zone_ids.add(zid)

    for w in warnings:
        logger.warning("Konfigurations-Warnung: %s", w)

    if errors:
        raise RuntimeError(
            f"Fehler in rooms.json ({len(errors)} Problem(e)):\n  "
            + "\n  ".join(f"• {e}" for e in errors)
        )

    return rooms


# ---------------------------------------------------------------------------
# Sensoren validieren
# ---------------------------------------------------------------------------

def load_sensors(rooms: Optional[list] = None) -> list:
    sensors = _load_json(CONFIG_DIR / "sensors.json")

    if not isinstance(sensors, list):
        raise RuntimeError("sensors.json: Inhalt muss eine JSON-Liste sein")

    room_map: dict = {}
    if rooms:
        room_map = {r["id"]: r for r in rooms if r.get("id")}

    errors: list = []
    warnings: list = []
    seen_ids: set = set()

    for i, sensor in enumerate(sensors):
        if not isinstance(sensor, dict):
            errors.append(f"Sensor[{i}]: muss ein JSON-Objekt sein")
            continue

        sid  = sensor.get("id")
        rid  = sensor.get("room_id")
        prefix = f"Sensor '{sid or f'[{i}]'}'"

        _require(errors, _is_nonempty_str(sid),
                 f"Sensor[{i}]: 'id' fehlt oder ist leer")
        _require(errors, _is_nonempty_str(sensor.get("name")),
                 f"{prefix}: 'name' fehlt oder ist leer")
        _require(errors, _is_nonempty_str(rid),
                 f"{prefix}: 'room_id' fehlt oder ist leer")
        _require(errors, isinstance(sensor.get("x_mm"), (int, float)),
                 f"{prefix}: 'x_mm' fehlt oder ist keine Zahl")
        _require(errors, isinstance(sensor.get("y_mm"), (int, float)),
                 f"{prefix}: 'y_mm' fehlt oder ist keine Zahl")
        _require(errors, _is_positive_number(sensor.get("mount_height_mm")),
                 f"{prefix}: 'mount_height_mm' muss eine positive Zahl sein")
        _require(errors, isinstance(sensor.get("rotation_deg"), (int, float)),
                 f"{prefix}: 'rotation_deg' fehlt oder ist keine Zahl")
        _require(errors, isinstance(sensor.get("enabled"), bool),
                 f"{prefix}: 'enabled' muss true oder false sein")

        if sid:
            if sid in seen_ids:
                errors.append(f"Sensor-ID '{sid}' ist doppelt vorhanden")
            else:
                seen_ids.add(sid)

        # room_id muss existieren
        if rid and room_map and rid not in room_map:
            errors.append(
                f"{prefix}: room_id='{rid}' existiert nicht in rooms.json\n"
                f"    Bekannte Räume: {', '.join(sorted(room_map.keys()))}"
            )

        # Sensor außerhalb des Raums → Warnung
        if rid and rid in room_map:
            room = room_map[rid]
            x = sensor.get("x_mm")
            y = sensor.get("y_mm")
            rw = room.get("width_mm", 0)
            rh = room.get("height_mm", 0)
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                if x < 0 or x > rw or y < 0 or y > rh:
                    warnings.append(
                        f"Sensor '{sid}': Position ({x}/{y} mm) liegt außerhalb "
                        f"von Raum '{rid}' ({rw}×{rh} mm)"
                    )

    for w in warnings:
        logger.warning("Konfigurations-Warnung: %s", w)

    if errors:
        raise RuntimeError(
            f"Fehler in sensors.json ({len(errors)} Problem(e)):\n  "
            + "\n  ".join(f"• {e}" for e in errors)
        )

    return sensors


# ---------------------------------------------------------------------------
# Einstellungen validieren
# ---------------------------------------------------------------------------

def load_settings() -> dict:
    settings = _load_json(CONFIG_DIR / "settings.json")

    if not isinstance(settings, dict):
        raise RuntimeError("settings.json: Inhalt muss ein JSON-Objekt sein")

    errors: list = []

    # mqtt
    mqtt = settings.get("mqtt")
    if not isinstance(mqtt, dict):
        errors.append("'mqtt' fehlt oder ist kein JSON-Objekt")
    else:
        _require(errors, _is_nonempty_str(mqtt.get("host")),
                 "mqtt.host: fehlt oder ist leer")
        _require(errors,
                 isinstance(mqtt.get("port"), int) and 1 <= mqtt["port"] <= 65535,
                 "mqtt.port: muss eine ganze Zahl zwischen 1 und 65535 sein")
        _require(errors, _is_nonempty_str(mqtt.get("topic")),
                 "mqtt.topic: fehlt oder ist leer")
        _require(errors, _is_positive_number(mqtt.get("reconnect_delay_seconds")),
                 "mqtt.reconnect_delay_seconds: muss eine positive Zahl sein")

    # database
    db = settings.get("database")
    if not isinstance(db, dict):
        errors.append("'database' fehlt oder ist kein JSON-Objekt")
    else:
        _require(errors, _is_nonempty_str(db.get("path")),
                 "database.path: fehlt oder ist leer")
        _require(errors, _is_positive_number(db.get("retention_days")),
                 "database.retention_days: muss eine positive Zahl sein")
        _require(errors, _is_positive_number(db.get("max_writes_per_second_per_sensor")),
                 "database.max_writes_per_second_per_sensor: muss eine positive Zahl sein")

    # websocket
    ws = settings.get("websocket")
    if not isinstance(ws, dict):
        errors.append("'websocket' fehlt oder ist kein JSON-Objekt")
    else:
        _require(errors, _is_positive_number(ws.get("broadcast_interval_ms")),
                 "websocket.broadcast_interval_ms: muss eine positive Zahl sein")

    # live
    live = settings.get("live")
    if not isinstance(live, dict):
        errors.append("'live' fehlt oder ist kein JSON-Objekt")
    else:
        _require(errors, _is_positive_number(live.get("sensor_offline_timeout_seconds")),
                 "live.sensor_offline_timeout_seconds: muss eine positive Zahl sein")
        _require(errors, _is_positive_number(live.get("recent_activity_timeout_seconds")),
                 "live.recent_activity_timeout_seconds: muss eine positive Zahl sein")

    # server
    srv = settings.get("server")
    if not isinstance(srv, dict):
        errors.append("'server' fehlt oder ist kein JSON-Objekt")
    else:
        _require(errors, _is_nonempty_str(srv.get("host")),
                 "server.host: fehlt oder ist leer")
        _require(errors,
                 isinstance(srv.get("port"), int) and 1 <= srv["port"] <= 65535,
                 "server.port: muss eine ganze Zahl zwischen 1 und 65535 sein")

    if errors:
        raise RuntimeError(
            f"Fehler in settings.json ({len(errors)} Problem(e)):\n  "
            + "\n  ".join(f"• {e}" for e in errors)
        )

    return settings
