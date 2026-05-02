"""
MQTT-Service für HausRadar.

Subscribed auf hausradar/sensor/+/state, verarbeitet eingehende
Sensor-Payloads identisch zu POST /api/simulate/motion und broadcastet
Updates per WebSocket an alle verbundenen Browser.
"""

import asyncio
import json
import logging
import threading
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt

from app.coordinate_transform import full_transform
from app import database as db
from app import live_state
from app import tracker as person_tracker
from app import door_detector
from app.websocket_service import manager as ws_manager

# Letzte bekannte Track-IDs pro Sensor (für Exit-Erkennung)
_prev_track_ids: Dict[str, Dict[int, dict]] = {}
_prev_lock = threading.Lock()

logger = logging.getLogger(__name__)


class MqttService:
    def __init__(self) -> None:
        self._client:     Optional[mqtt.Client] = None
        self._connected:  bool = False
        self._app:        Any  = None
        self._topic:      str  = ""

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self, app: Any) -> None:
        self._app = app
        cfg = app.state.settings.get("mqtt", {})
        host            = cfg.get("host", "localhost")
        port            = cfg.get("port", 1883)
        self._topic     = cfg.get("topic", "hausradar/sensor/+/state")
        reconnect_delay = cfg.get("reconnect_delay_seconds", 5)

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
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
        if self._client is None:
            return
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass
        logger.info("MQTT-Service gestoppt.")

    # ------------------------------------------------------------------
    # paho-Callbacks (laufen im MQTT-Thread)
    # ------------------------------------------------------------------

    def _on_connect(self, client: mqtt.Client, userdata: Any,
                    flags: dict, rc: int) -> None:
        if rc == 0:
            self._connected = True
            client.subscribe(self._topic)
            logger.info("MQTT verbunden, subscribed: %s", self._topic)
        else:
            logger.warning("MQTT Verbindung abgelehnt (rc=%d)", rc)

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        self._connected = False
        if rc != 0:
            logger.info("MQTT getrennt (rc=%d), warte auf Reconnect …", rc)

    def _on_message(self, client: mqtt.Client, userdata: Any,
                    msg: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as exc:
            logger.warning("MQTT Payload nicht lesbar: %s", exc)
            return
        # Verarbeitung in eigenem Thread, um MQTT-Loop nicht zu blockieren
        threading.Thread(target=self._process, args=(payload,), daemon=True).start()

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
                    room["width_mm"], room["height_mm"],
                )
            except Exception:
                pass  # Tür-Erkennung darf den Hauptpfad nie blockieren

            live_state.update(sensor_id, {
                "sensor_id":    sensor_id,
                "room_id":      room_id,
                "timestamp_ms": timestamp_ms,
                "target_count": len(real_targets),
                "targets":      all_targets,
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

        except Exception as exc:
            logger.warning("MQTT _process Fehler: %s", exc)

    def _detect_door_events(self, sensor_id: str, room_id: str,
                            tracked: list, room_w: float, room_h: float) -> None:
        """
        Vergleicht aktuelle Tracks mit dem letzten Frame.
        Verschwundene Tracks nahe einer Wand → Exit-Event.
        Neue echte Tracks die vorher nicht da waren → Entry-Event.

        Bug-Fix: prev speichert ALLE Tracks (real + Ghost), damit die letzte
        bekannte Position erhalten bleibt bis der Track komplett verschwindet.
        Vorher: prev enthielt nur reale Tracks → beim Ghost-Übergang wurde
        prev geleert → beim endgültigen Verschwinden war prev leer → kein Exit.
        """
        with _prev_lock:
            # Alle Tracks (real + Ghost) aus dem letzten Frame
            prev_all  = _prev_track_ids.get(sensor_id + ":all",  {})
            # Nur reale Tracks aus dem letzten Frame (für Entry-Erkennung)
            prev_real = _prev_track_ids.get(sensor_id + ":real", {})

            curr_all  = {t["track_id"]: t for t in tracked}
            curr_real = {t["track_id"]: t for t in tracked
                         if not t.get("ghost", False)}

            # Exits: Track war noch da (real oder Ghost), ist jetzt komplett weg
            for tid, t in prev_all.items():
                if tid not in curr_all:
                    door_detector.record_exit(
                        room_id,
                        t["room_x_mm"], t["room_y_mm"],
                        room_w, room_h,
                    )

            # Eintritte: neue echte Tracks (vorher weder real noch Ghost)
            for tid, t in curr_real.items():
                if tid not in prev_all:
                    door_detector.record_entry(room_id, t["room_x_mm"], t["room_y_mm"])

            _prev_track_ids[sensor_id + ":all"]  = curr_all
            _prev_track_ids[sensor_id + ":real"] = curr_real


# Globale Singleton-Instanz
service = MqttService()
