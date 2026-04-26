# HausRadar – Systemarchitektur

## Überblick

```
[HLK-LD2450] ──UART──► [ESP32]
                           │
                      WLAN / MQTT
                           │
               [Raspberry Pi Zero 2 W]
                           │
          ┌────────────────┼────────────────┐
          │                │                │
      FastAPI          SQLite           Mosquitto
      WebSocket        (Daten)          (MQTT-Broker)
          │
          └──► Browser: Grundriss + Live + Profile
```

## Komponenten

### ESP32 + HLK-LD2450
- Liest Radar-Rohdaten über UART (256000 Baud)
- Parst bis zu 3 Bewegungsziele pro Frame
- Sendet JSON-Payload alle 500 ms per MQTT

### Mosquitto (MQTT-Broker)
- Läuft lokal auf dem Raspberry Pi
- Topic-Schema: `hausradar/sensor/<sensor_id>/state`
- Availability: `hausradar/sensor/<sensor_id>/availability`

### FastAPI-Backend
- Empfängt MQTT-Nachrichten via paho-mqtt
- Rechnet Sensor-Koordinaten in Raum- und Grundriss-Koordinaten um
- Speichert Ereignisse in SQLite
- Verteilt Live-Daten über WebSocket an Browser

### SQLite-Datenbank
- Tabellen: sensor_events, target_positions, motion_sessions
- Automatische Bereinigung alter Daten (konfigurierbar)
- Schreibrate begrenzt für Raspberry Pi Zero 2 W

### Frontend
- Vanilla HTML/CSS/JavaScript – kein Framework
- SVG-Grundriss mit Live-Punkten und Spuren
- Analyse-Seite mit Diagrammen (Chart.js)
- WebSocket mit Auto-Reconnect

## Datenfluss

1. HLK-LD2450 sendet UART-Frame an ESP32
2. ESP32 parst Frame → JSON-Payload
3. ESP32 publiziert per MQTT an Broker
4. FastAPI empfängt MQTT-Nachricht
5. Koordinatenumrechnung: Sensor → Raum → Grundriss
6. Speicherung in SQLite (mit Rate-Limiting)
7. WebSocket-Broadcast an alle verbundenen Browser
8. Browser aktualisiert SVG-Grundriss in Echtzeit

## Payload-Format (ESP32 → Backend)

```json
{
  "sensor_id": "radar_wohnzimmer",
  "room_id": "wohnzimmer",
  "timestamp_ms": 1710000000000,
  "target_count": 1,
  "targets": [
    {
      "id": 1,
      "x_mm": 420,
      "y_mm": 2500,
      "speed_mm_s": 120,
      "distance_mm": 2535,
      "angle_deg": 9.5
    }
  ]
}
```
