"""
MQTT-Service für HausRadar.

Subscribed auf hausradar/sensor/+/state, verarbeitet eingehende
Sensor-Payloads identisch zu POST /api/simulate/motion und broadcastet
Updates per WebSocket an alle verbundenen Browser.
"""

import asyncio
import json
import logging
import queue
import threading
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt

from app.coordinate_transform import full_transform
from app import database as db
from app import live_state
from app import tracker as person_tracker
from app import door_detector
from app import transition_detector
from app import orientation_detector
from app import layout_engine
from app import auto_calibration
from app import furniture_detector
from app.websocket_service import manager as ws_manager

# Letzte bekannte Track-IDs pro Sensor (für Exit-Erkennung)
_prev_track_ids: Dict[str, Dict[int, dict]] = {}
_prev_lock = threading.Lock()

# Layout-Throttle: maximal alle 3s neu berechnen
import time as _time
_last_layout_ts: float = 0.0
_last_layout:    dict  = {}
_layout_lock     = threading.Lock()

# Auto-Kalibrierung: maximal alle 120s pro Sensor prüfen
_AUTO_APPLY_INTERVAL_S  = 120.0
_AUTO_APPLY_CONFIDENCE  = 0.65
_AUTO_APPLY_ROOM_DIFF   = 300   # mm – kleinere Änderungen ignorieren
_AUTO_APPLY_SENSOR_DIFF = 200   # mm – kleinere x_mm-Änderungen ignorieren
_auto_apply_ts: Dict[str, float] = {}
_auto_apply_lock  = threading.Lock()
_config_write_lock = threading.Lock()  # serialisiert Schreibzugriffe auf config/*.json

logger = logging.getLogger(__name__)


# Sentinel für sauberes Beenden des Worker-Threads
_QUEUE_SENTINEL = object()

# Maximale Anzahl gepufferter Sensor-Payloads. Bei Überlauf werden die
# ältesten verworfen – Live-Aktualität ist wichtiger als Vollständigkeit.
_INGEST_QUEUE_MAX = 500


class MqttService:
    def __init__(self) -> None:
        self._client:     Optional[mqtt.Client] = None
        self._connected:  bool = False
        self._app:        Any  = None
        self._topic:      str  = ""
        # Geordnete Single-Worker-Verarbeitung: bewahrt die Frame-Reihenfolge
        # (Tracker und Tür-Erkennung sind reihenfolgeabhängig) und vermeidet
        # unbegrenzte Thread-Erzeugung auf dem Raspberry Pi Zero 2 W.
        self._queue:      "queue.Queue" = queue.Queue(maxsize=_INGEST_QUEUE_MAX)
        self._worker:     Optional[threading.Thread] = None
        self._dropped:    int = 0

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    # LWT-Topic-Muster: hausradar/sensor/+/status
    # Der Sensor publiziert "online" beim Verbinden, der Broker publiziert
    # "offline" automatisch wenn die Verbindung unerwartet getrennt wird.
    _LWT_SUFFIX = "/status"

    def start(self, app: Any) -> None:
        self._app = app

        # Geordneten Verarbeitungs-Worker starten
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(
                target=self._worker_loop, name="mqtt-ingest", daemon=True
            )
            self._worker.start()

        cfg = app.state.settings.get("mqtt", {})
        host            = cfg.get("host", "localhost")
        port            = cfg.get("port", 1883)
        self._topic     = cfg.get("topic", "hausradar/sensor/+/state")
        reconnect_delay = cfg.get("reconnect_delay_seconds", 5)

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="hausradar-server",
        )
        client.reconnect_delay_set(min_delay=1, max_delay=reconnect_delay * 4)
        client.on_connect    = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message    = self._on_message
        self._client = client

        try:
            client.connect_async(host, port, keepalive=60)
            client.loop_start()
            logger.info("MQTT-Service gestartet (Broker: %s:%d, Topic: %s)",
                        host, port, self._topic)
        except Exception as exc:
            logger.warning("MQTT Verbindung nicht möglich: %s – Service läuft ohne Broker.", exc)

    def stop(self) -> None:
        # Worker beenden (auch wenn nie ein Broker verbunden war)
        if self._worker is not None and self._worker.is_alive():
            try:
                self._queue.put_nowait(_QUEUE_SENTINEL)
            except queue.Full:
                # Platz schaffen, damit das Sentinel sicher zugestellt wird
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                self._queue.put_nowait(_QUEUE_SENTINEL)
            self._worker.join(timeout=2.0)
            self._worker = None

        if self._client is None:
            return
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass
        logger.info("MQTT-Service gestoppt.")

    # ------------------------------------------------------------------
    # Geordneter Verarbeitungs-Worker
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        """Verarbeitet eingehende Payloads streng in Eingangsreihenfolge."""
        while True:
            payload = self._queue.get()
            if payload is _QUEUE_SENTINEL:
                break
            try:
                self._process(payload)
            except Exception as exc:
                logger.warning("MQTT-Worker Fehler: %s", exc)

    # ------------------------------------------------------------------
    # paho-Callbacks (laufen im MQTT-Thread)
    # ------------------------------------------------------------------

    def _on_connect(self, client: mqtt.Client, userdata: Any,
                    connect_flags, reason_code, properties=None) -> None:
        if reason_code == 0:
            self._connected = True
            client.subscribe(self._topic)
            # LWT-Topic: hausradar/sensor/+/status
            lwt_topic = self._topic.replace("/+/state", "/+/status")
            client.subscribe(lwt_topic)
            logger.info("MQTT verbunden, subscribed: %s + %s", self._topic, lwt_topic)
        else:
            logger.warning("MQTT Verbindung abgelehnt (reason_code=%s)", reason_code)

    def _on_disconnect(self, client: mqtt.Client, userdata: Any,
                       disconnect_flags, reason_code, properties=None) -> None:
        self._connected = False
        if reason_code != 0:
            logger.info("MQTT getrennt (reason_code=%s), warte auf Reconnect …", reason_code)

    def _on_message(self, client: mqtt.Client, userdata: Any,
                    msg: mqtt.MQTTMessage) -> None:
        topic = msg.topic

        # LWT-Status-Nachrichten direkt verarbeiten (kein JSON-Parse nötig)
        if topic.endswith(self._LWT_SUFFIX):
            parts = topic.split("/")
            # Format: hausradar/sensor/{sensor_id}/status
            if len(parts) >= 3:
                sensor_id = parts[-2]
                status    = msg.payload.decode("utf-8", errors="replace").strip()
                if status == "offline":
                    live_state.mark_offline(sensor_id)
                    logger.info("MQTT LWT: Sensor '%s' offline", sensor_id)
                elif status == "online":
                    logger.debug("MQTT LWT: Sensor '%s' online", sensor_id)
            return

        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as exc:
            logger.warning("MQTT Payload nicht lesbar: %s", exc)
            return
        # In die Verarbeitungs-Queue legen, damit der MQTT-Loop nicht blockiert
        # und die Frame-Reihenfolge erhalten bleibt. Bei Überlauf das älteste
        # Payload verwerfen (Live-Aktualität > Vollständigkeit).
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(payload)
            except queue.Full:
                pass
            self._dropped += 1
            if self._dropped % 100 == 1:
                logger.warning(
                    "MQTT-Ingest-Queue voll – %d Payload(s) verworfen", self._dropped
                )

    # ------------------------------------------------------------------
    # Payload verarbeiten (sync, in separatem Thread)
    # ------------------------------------------------------------------

    def _process(self, payload: Dict[str, Any]) -> None:
        app = self._app
        try:
            sensor_id    = payload.get("sensor_id")
            room_id      = payload.get("room_id")
            timestamp_ms = payload.get("timestamp_ms")
            targets_raw  = payload.get("targets", [])

            if not sensor_id or not room_id or timestamp_ms is None:
                logger.warning("MQTT: Pflichtfelder fehlen im Payload")
                return

            sensors = app.state.sensors
            rooms   = app.state.rooms

            sensor = next((s for s in sensors if s["id"] == sensor_id), None)
            if sensor is None:
                logger.warning("MQTT: Unbekannter Sensor '%s'", sensor_id)
                return

            if sensor["room_id"] != room_id:
                logger.warning("MQTT: room_id-Mismatch für Sensor '%s'", sensor_id)
                return

            room = next((r for r in rooms if r["id"] == room_id), None)
            if room is None:
                logger.warning("MQTT: Unbekannter Raum '%s'", room_id)
                return

            enriched = []
            for t in targets_raw:
                if t.get("y_mm", -1) < 0:
                    continue
                # Rohkoordinaten für Montage- und Auto-Kalibrierungs-Erkennung
                orientation_detector.update(sensor_id, t["x_mm"], t["y_mm"])
                auto_calibration.update(sensor_id, t["x_mm"], t["y_mm"])
                tf = full_transform(sensor, room,
                                    {"x_mm": t["x_mm"], "y_mm": t["y_mm"]})
                enriched.append({
                    "id":          t.get("id", 0),
                    "x_mm":        t["x_mm"],
                    "y_mm":        t["y_mm"],
                    "room_x_mm":   round(tf["room_x_mm"],  1),
                    "room_y_mm":   round(tf["room_y_mm"],  1),
                    "floorplan_x": round(tf["floorplan_x"], 3),
                    "floorplan_y": round(tf["floorplan_y"], 3),
                    "inside_room": tf["inside_room"],
                    "zone_id":     tf["zone_id"],
                    "speed_mm_s":  t.get("speed_mm_s",  0.0),
                    "distance_mm": t.get("distance_mm", 0.0),
                    "angle_deg":   t.get("angle_deg"),
                })

            # ── Personen-Tracking: stabile IDs, Ghost-Frames, Farben ──────────
            tracked = person_tracker.get_tracker(sensor_id).update(enriched)
            # Nur echte (nicht Ghost) Targets für DB und target_count
            real_targets = [t for t in tracked if not t.get("ghost", False)]
            # Alle Tracks (inkl. Ghosts) für WebSocket-Anzeige
            all_targets  = tracked

            # ── Tür-Erkennung: Exits und Eintritte registrieren ───────────────
            try:
                self._detect_door_events(
                    sensor_id, room_id, tracked,
                    room["width_mm"], room["height_mm"], app,
                )
            except Exception as exc:
                logger.warning("_detect_door_events Fehler: %s", exc, exc_info=True)

            live_state.update(sensor_id, {
                "sensor_id":    sensor_id,
                "room_id":      room_id,
                "timestamp_ms": timestamp_ms,
                "target_count": len(real_targets),
                "targets":      all_targets,
                "cal_phase":    auto_calibration.get_phase(sensor_id),
            })

            # DB schreiben (sync, rate-limited) – keine Ghost-Targets
            max_writes = app.state.settings.get("database", {}).get(
                "max_writes_per_second_per_sensor", 2
            )
            try:
                db.record_motion(app.state.db_path, sensor_id, room_id,
                                 timestamp_ms, real_targets, max_writes)
            except Exception as exc:
                logger.warning("MQTT DB-Schreiben fehlgeschlagen: %s", exc)

            # WebSocket-Broadcast (async → Event-Loop des Hauptthreads)
            if ws_manager.connection_count > 0:
                timeout = app.state.settings.get("live", {}).get(
                    "sensor_offline_timeout_seconds", 10
                )
                response = live_state.build_response(timeout)
                try:
                    asyncio.run_coroutine_threadsafe(
                        ws_manager.broadcast(response),
                        app.state.event_loop,
                    )
                except Exception as exc:
                    logger.warning("MQTT WS-Broadcast fehlgeschlagen: %s", exc)

            logger.debug("MQTT verarbeitet: sensor=%s targets=%d",
                         sensor_id, len(enriched))

            # Auto-Kalibrierung periodisch prüfen (blockierungsfrei)
            self._schedule_auto_apply(sensor_id, room_id)

        except Exception as exc:
            logger.warning("MQTT _process Fehler: %s", exc)

    def _maybe_push_layout_update(self, app: Any) -> None:
        """Berechnet das Live-Layout neu wenn nötig und pusht es als WS-Event."""
        global _last_layout_ts, _last_layout
        now = _time.time()
        with _layout_lock:
            if now - _last_layout_ts < 3.0:
                return
            _last_layout_ts = now

        try:
            rooms    = app.state.rooms
            conns    = transition_detector.get_connections()
            new_layout = layout_engine.compute(rooms, conns)
            with _layout_lock:
                if not layout_engine.layout_changed(_last_layout, new_layout):
                    return
                _last_layout = dict(new_layout)

            live_state.push_event({
                "type":   "layout_update",
                "layout": new_layout,
            })
        except Exception as exc:
            logger.warning("_maybe_push_layout_update Fehler: %s", exc)

    def _detect_door_events(self, sensor_id: str, room_id: str,
                            tracked: list, room_w: float, room_h: float,
                            app: Any = None) -> None:
        """
        Vergleicht aktuelle Tracks mit dem letzten Frame.
        Exit-Events werden auf zwei Arten erkannt:
          1. Track verschwindet komplett (war nahe Wand)
          2. Track war inside_room=True, ist jetzt inside_room=False
             (Person verlässt Raumgrenze, auch wenn Sensor sie noch verfolgt)
        Neue echte Tracks die vorher nicht da waren → Entry-Event.
        """
        with _prev_lock:
            # Alle Tracks (real + Ghost) aus dem letzten Frame
            prev_all  = _prev_track_ids.get(sensor_id + ":all",  {})
            # Nur reale Tracks aus dem letzten Frame (für Entry-Erkennung)
            prev_real = _prev_track_ids.get(sensor_id + ":real", {})

            curr_all  = {t["track_id"]: t for t in tracked}
            curr_real = {t["track_id"]: t for t in tracked
                         if not t.get("ghost", False)}

            # Exit-Variante 1: Track komplett verschwunden (war noch da, jetzt weg)
            for tid, t in prev_all.items():
                if tid not in curr_all:
                    door_detector.record_exit(
                        room_id,
                        t["room_x_mm"], t["room_y_mm"],
                        room_w, room_h,
                    )
                    transition_detector.record_exit(room_id)

            # Exit-Variante 2: Track noch da, aber gerade aus Raumgrenze heraus
            # Nutzt letzte bekannte Position IN der Raumgrenze (prev-Frame)
            for tid, t_curr in curr_all.items():
                if t_curr.get("ghost"):
                    continue
                t_prev = prev_all.get(tid)
                if t_prev is None:
                    continue
                was_inside = t_prev.get("inside_room", True)
                is_inside  = t_curr.get("inside_room", True)
                if was_inside and not is_inside:
                    door_detector.record_exit(
                        room_id,
                        t_prev["room_x_mm"], t_prev["room_y_mm"],
                        room_w, room_h,
                    )
                    transition_detector.record_exit(room_id)

            # Eintritte: neue echte Tracks (vorher weder real noch Ghost)
            # ODER Track war draußen und ist jetzt (wieder) drinnen
            _new_transit = False
            for tid, t in curr_real.items():
                if tid not in prev_all:
                    door_detector.record_entry(room_id, t["room_x_mm"], t["room_y_mm"])
                    transit = transition_detector.record_entry(room_id)
                    if transit:
                        live_state.push_event(transit)
                        _new_transit = True
                else:
                    t_prev = prev_all[tid]
                    if not t_prev.get("inside_room", True) and t.get("inside_room", True):
                        door_detector.record_entry(room_id, t["room_x_mm"], t["room_y_mm"])
                        transit = transition_detector.record_entry(room_id)
                        if transit:
                            live_state.push_event(transit)
                            _new_transit = True

            if _new_transit and app is not None:
                self._maybe_push_layout_update(app)

            # Möbel-Dwell-Erkennung: verschwundene echte Tracks melden
            disappeared_real = [tid for tid in prev_real if tid not in curr_real]
            furniture_detector.update_tracks(
                sensor_id, room_id,
                list(curr_real.values()),
                disappeared_real,
            )

            _prev_track_ids[sensor_id + ":all"]  = curr_all
            _prev_track_ids[sensor_id + ":real"] = curr_real


    # ------------------------------------------------------------------
    # Auto-Kalibrierung (M24)
    # ------------------------------------------------------------------

    def _schedule_auto_apply(self, sensor_id: str, room_id: str) -> None:
        """Startet Auto-Kalibrierung in eigenem Thread wenn Intervall abgelaufen."""
        now = _time.time()
        with _auto_apply_lock:
            if now - _auto_apply_ts.get(sensor_id, 0) < _AUTO_APPLY_INTERVAL_S:
                return
            _auto_apply_ts[sensor_id] = now
        threading.Thread(
            target=self._do_auto_apply,
            args=(sensor_id, room_id),
            daemon=True,
        ).start()

    def _do_auto_apply(self, sensor_id: str, room_id: str) -> None:
        try:
            with _config_write_lock:
                events = self._apply_calibration_if_improved(sensor_id, room_id)
            for ev in events:
                live_state.push_event(ev)
            if events:
                self._maybe_push_layout_update(self._app)
        except Exception as exc:
            logger.warning("Auto-Kalibrierung Fehler (%s): %s", sensor_id, exc, exc_info=True)

    def _apply_calibration_if_improved(self, sensor_id: str, room_id: str) -> list:
        """
        Prüft M23 (Raumgröße) und M21 (Sensorparameter).
        Wendet an wenn Konfidenz ≥ Schwellwert und Änderung nennenswert.
        Gibt Liste von calibration_update-Events zurück.
        """
        from pathlib import Path
        from app.config import load_rooms, load_sensors
        from app.config_io import load_json, save_json

        app = self._app
        if app is None:
            return []

        cfg_dir      = Path(__file__).resolve().parent.parent.parent / "config"
        rooms_path   = cfg_dir / "rooms.json"
        sensors_path = cfg_dir / "sensors.json"
        events: list = []

        # ── M23: Raumgröße automatisch ermitteln ──────────────────────────
        rs = auto_calibration.suggest_room_size(sensor_id)
        if rs and rs.get("confidence", 0) >= _AUTO_APPLY_CONFIDENCE:
            room = next((r for r in app.state.rooms if r["id"] == room_id), None)
            if room:
                curr_w, curr_h = room.get("width_mm", 0), room.get("height_mm", 0)
                new_w,  new_h  = rs["width_mm"],          rs["height_mm"]
                if abs(new_w - curr_w) > _AUTO_APPLY_ROOM_DIFF or \
                   abs(new_h - curr_h) > _AUTO_APPLY_ROOM_DIFF:
                    rooms_data = load_json(rooms_path)
                    for r in rooms_data:
                        if r["id"] == room_id:
                            r["width_mm"]  = new_w
                            r["height_mm"] = new_h
                            break
                    save_json(rooms_path, rooms_data)
                    app.state.rooms   = load_rooms()
                    app.state.sensors = load_sensors(app.state.rooms)
                    logger.info(
                        "Auto-Cal Raumgröße %s: %d×%d → %d×%d mm (conf=%.2f)",
                        room_id, curr_w, curr_h, new_w, new_h, rs["confidence"],
                    )
                    w_m = f"{new_w / 1000:.1f}"
                    h_m = f"{new_h / 1000:.1f}"
                    events.append({
                        "type":       "calibration_update",
                        "subtype":    "room_size",
                        "room_id":    room_id,
                        "width_mm":   new_w,
                        "height_mm":  new_h,
                        "confidence": rs["confidence"],
                        "msg":        f"Raumgröße ermittelt: {w_m} × {h_m} m",
                    })

        # ── M21: Sensorparameter automatisch ermitteln ────────────────────
        rooms   = app.state.rooms  # ggf. frisch geladen nach M23
        sensors = app.state.sensors
        room    = next((r for r in rooms   if r["id"]  == room_id),   None)
        sensor  = next((s for s in sensors if s["id"]  == sensor_id), None)
        if room and sensor:
            cal = auto_calibration.suggest(sensor_id, room)
            if cal and cal.get("confidence", 0) >= _AUTO_APPLY_CONFIDENCE:
                new_rot  = cal["rotation_deg"]
                new_x    = cal["sensor_x_mm"]
                curr_rot = sensor.get("rotation_deg", 0)
                curr_x   = sensor.get("x_mm", 0)
                if new_rot != curr_rot or abs(new_x - curr_x) > _AUTO_APPLY_SENSOR_DIFF:
                    sensors_data = load_json(sensors_path)
                    for s in sensors_data:
                        if s["id"] == sensor_id:
                            s["rotation_deg"] = new_rot
                            s["x_mm"]         = new_x
                            s["y_mm"]         = cal["sensor_y_mm"]
                            break
                    save_json(sensors_path, sensors_data)
                    app.state.sensors = load_sensors(app.state.rooms)
                    logger.info(
                        "Auto-Cal Sensor %s: rot %d°→%d°, x %d→%d mm (conf=%.2f)",
                        sensor_id, curr_rot, new_rot, curr_x, new_x, cal["confidence"],
                    )
                    events.append({
                        "type":         "calibration_update",
                        "subtype":      "sensor",
                        "sensor_id":    sensor_id,
                        "rotation_deg": new_rot,
                        "sensor_x_mm":  new_x,
                        "confidence":   cal["confidence"],
                        "msg":          f"Sensor kalibriert: {new_rot}°",
                    })

        # ── M25: Raumform (Polygon) aus Belegungsraster lernen ────────────
        rooms   = app.state.rooms
        sensors = app.state.sensors
        room    = next((r for r in rooms   if r["id"] == room_id),   None)
        sensor  = next((s for s in sensors if s["id"] == sensor_id), None)
        if room and sensor:
            shape = auto_calibration.suggest_room_shape(sensor_id, room, sensor)
            if shape and shape.get("confidence", 0) >= _AUTO_APPLY_CONFIDENCE:
                new_pts = shape["shape_points"]
                if new_pts != room.get("shape_points"):
                    rooms_data = load_json(rooms_path)
                    for r in rooms_data:
                        if r["id"] == room_id:
                            r["shape_points"] = new_pts
                            break
                    save_json(rooms_path, rooms_data)
                    app.state.rooms   = load_rooms()
                    app.state.sensors = load_sensors(app.state.rooms)
                    logger.info(
                        "Auto-Cal Raumform %s: %d Wandsegmente (conf=%.2f)",
                        room_id, shape["segments"], shape["confidence"],
                    )
                    events.append({
                        "type":       "calibration_update",
                        "subtype":    "room_shape",
                        "room_id":    room_id,
                        "confidence": shape["confidence"],
                        "msg":        "Raumform erkannt und übernommen",
                    })

        return events


# Globale Singleton-Instanz
service = MqttService()
