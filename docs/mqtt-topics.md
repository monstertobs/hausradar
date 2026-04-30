# HausRadar – MQTT-Topics & Payload-Formate

## Topic-Schema

```
hausradar/sensor/<sensor_id>/state        ← Bewegungsdaten (vom ESP32)
hausradar/sensor/<sensor_id>/availability ← Online/Offline-Status
```

Die `<sensor_id>` muss exakt mit dem `id`-Feld in `config/sensors.json` übereinstimmen.  
Sie wird in der ESP32-Firmware unter `SENSOR_ID` in `include/config.h` konfiguriert.  
Das vollständige Topic ist in der Weboberfläche unter **Einstellungen → Sensoren** einsehbar.

---

## Sensor-Daten (ESP32 → Backend)

**Topic:** `hausradar/sensor/radar_wohnzimmer/state`  
**QoS:** 0 · **Retain:** nein · **Intervall:** 500 ms (konfigurierbar)

```json
{
  "sensor_id": "radar_wohnzimmer",
  "room_id": "wohnzimmer",
  "timestamp_ms": 1710000000000,
  "target_count": 2,
  "targets": [
    {
      "id": 1,
      "x_mm": 420,
      "y_mm": 2500,
      "speed_mm_s": 120,
      "distance_mm": 2535,
      "angle_deg": 9.5
    },
    {
      "id": 2,
      "x_mm": -300,
      "y_mm": 1800,
      "speed_mm_s": 0,
      "distance_mm": 1825,
      "angle_deg": -9.4
    }
  ]
}
```

**Felder:**

| Feld | Typ | Beschreibung |
|---|---|---|
| `sensor_id` | string | Eindeutige Sensor-ID (muss zu `sensors.json` passen) |
| `room_id` | string | Raum-ID (muss zu `rooms.json` passen) |
| `timestamp_ms` | int | Unix-Timestamp in Millisekunden (NTP oder `millis()`-Fallback) |
| `target_count` | int | Anzahl erkannter Ziele (0–3) |
| `targets[].id` | int | Target-Slot-ID des LD2450 (1–3) |
| `targets[].x_mm` | int | X-Koordinate relativ zum Sensor [mm] |
| `targets[].y_mm` | int | Y-Koordinate relativ zum Sensor (Entfernung) [mm] |
| `targets[].speed_mm_s` | int | Radialgeschwindigkeit [mm/s], negativ = wegbewegend |
| `targets[].distance_mm` | int | Euklidischer Abstand zum Sensor [mm] |
| `targets[].angle_deg` | float | Winkel vom Sensor aus gesehen [°] |

---

## Anreicherter WebSocket-Payload (Backend → Browser)

Das Backend verarbeitet die Rohdaten und sendet über `/ws/live` und `GET /api/live`
deutlich reichhaltigere Informationen:

```json
{
  "timestamp_ms": 1710000000000,
  "sensor_count": 1,
  "sensors": {
    "radar_wohnzimmer": {
      "sensor_id": "radar_wohnzimmer",
      "room_id": "wohnzimmer",
      "target_count": 2,
      "online": true,
      "last_seen_seconds_ago": 0.12,
      "targets": [
        {
          "id": 1,
          "x_mm": 420,
          "y_mm": 2500,
          "room_x_mm": 1245.3,
          "room_y_mm": 3102.7,
          "floorplan_x": 142.3,
          "floorplan_y": 275.1,
          "inside_room": true,
          "zone_id": "sofa",
          "speed_mm_s": 120,
          "distance_mm": 2535,
          "angle_deg": 9.5,
          "track_id": 7,
          "color_idx": 0,
          "ghost": false
        }
      ]
    }
  }
}
```

**Zusätzliche Felder im angereicherten Payload:**

| Feld | Typ | Beschreibung |
|---|---|---|
| `online` | bool | `true` wenn Sensor innerhalb des Timeout gesehen wurde |
| `last_seen_seconds_ago` | float | Sekunden seit dem letzten MQTT-Paket |
| `room_x_mm` | float | Koordinate im Raum-Koordinatensystem [mm] |
| `room_y_mm` | float | Koordinate im Raum-Koordinatensystem [mm] |
| `floorplan_x` | float | SVG-Pixel im Grundriss (direkt verwendbar) |
| `floorplan_y` | float | SVG-Pixel im Grundriss (direkt verwendbar) |
| `inside_room` | bool | `false` wenn Ziel außerhalb der Raumgrenzen liegt |
| `zone_id` | string\|null | ID der Zone in der sich das Ziel befindet |
| `track_id` | int | Stabile Personen-ID über Frames hinweg (setzt sich bei Service-Neustart zurück) |
| `color_idx` | 0/1/2 | Farb-Index: 0=blau, 1=orange, 2=grün |
| `ghost` | bool | `true` = kein aktuelles Signal, überbrückte Position (max. 4 Frames) |

---

## Availability

**Topic:** `hausradar/sensor/radar_wohnzimmer/availability`  
**QoS:** 1 · **Retain:** ja

Werte: `online` | `offline`

Der ESP32 sendet beim Start `online` und konfiguriert `offline` als Last-Will-Testament (LWT).

> **Hinweis:** Das Backend erkennt Sensor-Offline-Zustände auch ohne LWT über einen
> konfigurierbaren Timeout (`settings.live.sensor_offline_timeout_seconds`, Standard: 10 s).

---

## Mosquitto-Test

```bash
# Alle HausRadar-Nachrichten live beobachten
mosquitto_sub -h localhost -t "hausradar/#" -v

# Nur Bewegungsdaten
mosquitto_sub -h localhost -t "hausradar/sensor/+/state" -v

# Testdaten manuell einspeisen
mosquitto_pub -h localhost \
  -t "hausradar/sensor/radar_wohnzimmer/state" \
  -m '{
    "sensor_id": "radar_wohnzimmer",
    "room_id": "wohnzimmer",
    "timestamp_ms": 0,
    "target_count": 1,
    "targets": [{"id":1,"x_mm":0,"y_mm":2000,"speed_mm_s":0,"distance_mm":2000,"angle_deg":0}]
  }'
```
