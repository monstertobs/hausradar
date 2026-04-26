#!/usr/bin/env python3
"""HausRadar – Sensor-Datensimulation

Erzeugt künstliche Bewegungsdaten für alle konfigurierten Sensoren und
sendet sie per HTTP POST oder MQTT an das Backend.

Verwendung:
    python3 scripts/simulate_sensor_data.py
    python3 scripts/simulate_sensor_data.py --host 192.168.1.100 --port 8000
    python3 scripts/simulate_sensor_data.py --interval 0.2 --verbose
    python3 scripts/simulate_sensor_data.py --mqtt
    python3 scripts/simulate_sensor_data.py --mqtt --mqtt-host 192.168.1.50
"""

import argparse
import json
import math
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR  = PROJECT_DIR / "config"


# ---------------------------------------------------------------------------
# Config laden (minimale Version ohne Validierung – nur stdlib)
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> object:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_config():
    rooms   = _load_json(CONFIG_DIR / "rooms.json")
    sensors = _load_json(CONFIG_DIR / "sensors.json")
    room_map = {r["id"]: r for r in rooms}
    return room_map, [s for s in sensors if s.get("enabled", True)]


# ---------------------------------------------------------------------------
# Mathematik: Raumkoordinaten → Sensorkoordinaten (Inverse Transformation)
#
# Die Vorwärts-Transformation in coordinate_transform.py ist:
#   x_room = sx + xs·cos(θ) + ys·sin(θ)
#   y_room = sy − xs·sin(θ) + ys·cos(θ)
#
# Inverse (R⁻¹ = Rᵀ für orthogonale Matrix):
#   xs = (rx−sx)·cos(θ) − (ry−sy)·sin(θ)
#   ys = (rx−sx)·sin(θ) + (ry−sy)·cos(θ)
# ---------------------------------------------------------------------------

def room_to_sensor(sensor: dict, room_x: float, room_y: float):
    theta = math.radians(sensor["rotation_deg"])
    dx = room_x - sensor["x_mm"]
    dy = room_y - sensor["y_mm"]
    xs = dx * math.cos(theta) - dy * math.sin(theta)
    ys = dx * math.sin(theta) + dy * math.cos(theta)
    return xs, ys


# ---------------------------------------------------------------------------
# Walker: bewegt sich durch einen Raum und prallt an Wänden ab
# ---------------------------------------------------------------------------

class Walker:
    SPEED_MIN_MM_S = 80.0
    SPEED_MAX_MM_S = 300.0
    DIRECTION_CHANGE_PROB = 0.04   # Chance pro Step auf Richtungsänderung
    DIRECTION_CHANGE_MAX_RAD = 0.6

    def __init__(self, room: dict, target_id: int = 1):
        self.room      = room
        self.target_id = target_id
        w = room["width_mm"]
        h = room["height_mm"]
        margin = 0.15
        self.x = random.uniform(w * margin, w * (1 - margin))
        self.y = random.uniform(h * margin, h * (1 - margin))
        speed  = random.uniform(self.SPEED_MIN_MM_S, self.SPEED_MAX_MM_S)
        angle  = random.uniform(0, 2 * math.pi)
        self.vx = speed * math.cos(angle)
        self.vy = speed * math.sin(angle)

    def step(self, dt: float) -> None:
        self.x += self.vx * dt
        self.y += self.vy * dt
        w = self.room["width_mm"]
        h = self.room["height_mm"]

        # Wandreflexion – Position korrigieren damit Walker im Raum bleibt
        if self.x < 0:
            self.x  = -self.x
            self.vx = abs(self.vx)
        elif self.x > w:
            self.x  = 2 * w - self.x
            self.vx = -abs(self.vx)

        if self.y < 0:
            self.y  = -self.y
            self.vy = abs(self.vy)
        elif self.y > h:
            self.y  = 2 * h - self.y
            self.vy = -abs(self.vy)

        # Gelegentliche Richtungsänderung
        if random.random() < self.DIRECTION_CHANGE_PROB:
            delta = random.uniform(
                -self.DIRECTION_CHANGE_MAX_RAD,
                 self.DIRECTION_CHANGE_MAX_RAD,
            )
            speed = math.hypot(self.vx, self.vy)
            angle = math.atan2(self.vy, self.vx) + delta
            self.vx = speed * math.cos(angle)
            self.vy = speed * math.sin(angle)

    @property
    def speed_mm_s(self) -> float:
        return math.hypot(self.vx, self.vy)


# ---------------------------------------------------------------------------
# Payload bauen
# ---------------------------------------------------------------------------

def build_payload(sensor: dict, walker: Walker, timestamp_ms: int) -> dict:
    xs, ys = room_to_sensor(sensor, walker.x, walker.y)

    # ys < 0 bedeutet Ziel hinter dem Sensor – in der Praxis würde LD2450
    # solche Ziele nicht melden. Wir klemmen auf 0 mm Mindestabstand.
    ys = max(ys, 0.0)

    distance = math.hypot(xs, ys)
    angle    = math.degrees(math.atan2(xs, ys)) if distance > 1.0 else 0.0

    return {
        "sensor_id":   sensor["id"],
        "room_id":     sensor["room_id"],
        "timestamp_ms": timestamp_ms,
        "target_count": 1,
        "targets": [
            {
                "id":          walker.target_id,
                "x_mm":        round(xs, 1),
                "y_mm":        round(ys, 1),
                "speed_mm_s":  round(walker.speed_mm_s, 1),
                "distance_mm": round(distance, 1),
                "angle_deg":   round(angle, 2),
            }
        ],
    }


# ---------------------------------------------------------------------------
# HTTP senden
# ---------------------------------------------------------------------------

def post_json(url: str, data: dict, timeout: float = 2.0) -> int:
    body = json.dumps(data).encode("utf-8")
    req  = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


# ---------------------------------------------------------------------------
# MQTT senden
# ---------------------------------------------------------------------------

def _make_mqtt_client(host: str, port: int, settings_path: Path):
    """Baut einen paho-mqtt-Client auf und returned ihn (verbunden)."""
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        print("paho-mqtt nicht installiert. Bitte: pip install paho-mqtt", file=sys.stderr)
        sys.exit(1)

    topic_template = "hausradar/sensor/{sensor_id}/state"
    try:
        cfg = json.loads((settings_path / "settings.json").read_text(encoding="utf-8"))
        topic_template = cfg.get("mqtt", {}).get("topic", topic_template)
    except Exception:
        pass

    connected = [False]

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            connected[0] = True
        else:
            print(f"MQTT Verbindung abgelehnt (rc={rc})", file=sys.stderr)
            sys.exit(1)

    client = mqtt.Client(client_id="hausradar-sim")
    client.on_connect = on_connect
    client.connect(host, port, keepalive=60)
    client.loop_start()

    deadline = time.monotonic() + 5.0
    while not connected[0] and time.monotonic() < deadline:
        time.sleep(0.05)

    if not connected[0]:
        print(f"MQTT Verbindung zu {host}:{port} nicht möglich.", file=sys.stderr)
        sys.exit(1)

    # Sensor-ID aus dem Topic-Template extrahieren → publish-Topic bauen
    # Template: "hausradar/sensor/+/state" → "hausradar/sensor/{id}/state"
    def publish(payload: dict) -> None:
        sid   = payload["sensor_id"]
        topic = topic_template.replace("+", sid).replace("{sensor_id}", sid)
        client.publish(topic, json.dumps(payload), qos=0)

    return client, publish


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="HausRadar Sensor-Simulation",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host",      default="localhost",
                        help="Backend-Host (HTTP)")
    parser.add_argument("--port",      type=int, default=8000,
                        help="Backend-Port (HTTP)")
    parser.add_argument("--interval",  type=float, default=0.5,
                        help="Sekunden zwischen Datenpunkten pro Sensor")
    parser.add_argument("--verbose",   action="store_true",
                        help="Koordinaten für jeden Sensor ausgeben")
    parser.add_argument("--mqtt",      action="store_true",
                        help="Daten per MQTT statt HTTP senden")
    parser.add_argument("--mqtt-host", default="localhost",
                        help="MQTT-Broker-Host")
    parser.add_argument("--mqtt-port", type=int, default=1883,
                        help="MQTT-Broker-Port")
    args = parser.parse_args()

    try:
        room_map, active_sensors = load_config()
    except FileNotFoundError as e:
        print(f"Fehler: Konfigurationsdatei nicht gefunden: {e}", file=sys.stderr)
        sys.exit(1)

    if not active_sensors:
        print("Keine aktiven Sensoren konfiguriert.", file=sys.stderr)
        sys.exit(1)

    # Transport einrichten
    if args.mqtt:
        _mqtt_client, send = _make_mqtt_client(
            args.mqtt_host, args.mqtt_port, CONFIG_DIR
        )
        transport_label = f"MQTT  {args.mqtt_host}:{args.mqtt_port}"
    else:
        motion_url = f"http://{args.host}:{args.port}/api/simulate/motion"
        transport_label = f"HTTP  {motion_url}"

        def send(payload: dict) -> None:
            status = post_json(motion_url, payload)
            if status != 200:
                raise RuntimeError(f"HTTP {status}")

    # Walker für jeden aktiven Sensor
    walkers = {
        s["id"]: Walker(room_map[s["room_id"]])
        for s in active_sensors
    }

    print("HausRadar Simulation")
    print(f"  Transport: {transport_label}")
    print(f"  Sensoren:  {[s['id'] for s in active_sensors]}")
    print(f"  Intervall: {args.interval} s   |   Strg+C zum Beenden\n")

    consecutive_errors = 0
    last_tick = time.monotonic()

    while True:
        now  = time.monotonic()
        dt   = now - last_tick
        last_tick = now
        timestamp_ms = int(time.time() * 1000)

        for sensor in active_sensors:
            walker  = walkers[sensor["id"]]
            walker.step(dt)
            payload = build_payload(sensor, walker, timestamp_ms)

            try:
                send(payload)
                consecutive_errors = 0
                if args.verbose:
                    t = payload["targets"][0]
                    print(
                        f"  {sensor['id']:25s}  "
                        f"Raum ({walker.x:6.0f}, {walker.y:6.0f}) mm  "
                        f"Sensor ({t['x_mm']:7.1f}, {t['y_mm']:7.1f}) mm  "
                        f"Zone: {_zone_label(sensor, room_map, walker)}"
                    )
            except urllib.error.URLError as exc:
                consecutive_errors += 1
                _log_error(consecutive_errors, sensor["id"],
                           f"Verbindungsfehler: {exc.reason}")
            except Exception as exc:
                consecutive_errors += 1
                _log_error(consecutive_errors, sensor["id"], str(exc))

        if not args.verbose:
            parts = []
            for sensor in active_sensors:
                w = walkers[sensor["id"]]
                parts.append(f"{sensor['room_id']}:({w.x:.0f},{w.y:.0f})")
            print("  " + "  |  ".join(parts), end="\r", flush=True)

        time.sleep(args.interval)


def _zone_label(sensor: dict, room_map: dict, walker: Walker) -> str:
    room  = room_map.get(sensor["room_id"], {})
    zones = room.get("zones", [])
    for z in zones:
        if (z["x_mm"] <= walker.x <= z["x_mm"] + z["width_mm"] and
                z["y_mm"] <= walker.y <= z["y_mm"] + z["height_mm"]):
            return z["name"]
    return "–"


def _log_error(count: int, sensor_id: str, msg: str) -> None:
    if count <= 5 or count % 20 == 0:
        print(f"\n  [{sensor_id}] Fehler #{count}: {msg}", flush=True)
    if count == 5:
        print("  (Weitere Fehler werden seltener ausgegeben …)", flush=True)


if __name__ == "__main__":
    main()
