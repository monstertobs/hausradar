# HausRadar – MQTT-Topics

## Schema

```
hausradar/sensor/<sensor_id>/state        ← Bewegungsdaten
hausradar/sensor/<sensor_id>/availability ← Online/Offline
```

## Sensor-Daten

**Topic:** `hausradar/sensor/radar_wohnzimmer/state`  
**QoS:** 0  
**Retain:** nein

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

## Availability

**Topic:** `hausradar/sensor/radar_wohnzimmer/availability`  
**QoS:** 1  
**Retain:** ja

Werte: `online` | `offline`

Der ESP32 sendet beim Start `online` und konfiguriert `offline` als Last-Will-Testament (LWT).

## Mosquitto-Test

```bash
# Alle HausRadar-Nachrichten beobachten
mosquitto_sub -t "hausradar/#" -v

# Testdaten manuell einspeisen
mosquitto_pub -t "hausradar/sensor/radar_wohnzimmer/state" \
  -m '{"sensor_id":"radar_wohnzimmer","room_id":"wohnzimmer","timestamp_ms":0,"target_count":0,"targets":[]}'
```
