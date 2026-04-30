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
- Konfiguration: `firmware/esp32-ld2450-mqtt/include/config.h`
- Zugangsdaten (WLAN, MQTT): `include/secrets.h` (gitignored)

### Mosquitto (MQTT-Broker)
- Läuft lokal auf dem Raspberry Pi
- Topic-Schema: `hausradar/sensor/<sensor_id>/state`
- Availability: `hausradar/sensor/<sensor_id>/availability`
- Konfiguration: `deploy/mosquitto-hausradar.conf`

### FastAPI-Backend
- Empfängt MQTT-Nachrichten via paho-mqtt (`mqtt_service.py`)
- Rechnet Sensor-Koordinaten in Raum- und Grundriss-Koordinaten um (`coordinate_transform.py`)
- **Personen-Tracking**: weist stabilen Track-IDs + Farben zu (`tracker.py`)
- Speichert Ereignisse in SQLite (`database.py`)
- Verteilt Live-Daten über WebSocket an Browser (`websocket_service.py`)
- Web-Update-Manager: Git-Pull + pip + Rollback + Service-Neustart (`api/update.py`)

### Personen-Tracker (`tracker.py`)
- Greedy Nearest-Neighbour in Raum-Koordinaten (max. 800 mm Zuordnungsdistanz)
- Pro Sensor eine `PersonTracker`-Instanz, thread-sicher via Lock
- Ghost-Frames: bis zu 4 verpasste Frames werden mit letzter bekannter Position gehalten
- Farb-IDs: 0=blau, 1=orange, 2=grün – stabil solange die Person im Raum bleibt

### SQLite-Datenbank
- Tabellen: `sensor_events`, `target_positions`, `motion_sessions`
- Automatische Bereinigung alter Daten (konfigurierbar via `retention_days`)
- Schreibrate begrenzt für Raspberry Pi Zero 2 W (`max_writes_per_second_per_sensor`)
- WAL-Mode + `synchronous=NORMAL` für bessere Concurrent-Performance

### Frontend
- Vanilla HTML/CSS/JavaScript – kein Framework
- SVG-Grundriss mit Live-Punkten, Spuren und Personen-Farbkodierung
- Analyse-Seite mit Diagrammen (Chart.js)
- WebSocket mit Auto-Reconnect
- Versions-Badge in der Topbar (geladen via `/api/health`)

---

## Datenfluss

```
1. HLK-LD2450 sendet UART-Frame an ESP32
2. ESP32 parst Frame → JSON-Payload (bis zu 3 Targets mit x_mm, y_mm, speed, …)
3. ESP32 publiziert per MQTT an Broker (hausradar/sensor/<id>/state)
4. FastAPI mqtt_service._on_message() → Thread: _process()
5. coordinate_transform.full_transform():
      Sensor-Koordinaten → Raum-Koordinaten → Grundriss-Pixel + Zone
6. tracker.get_tracker(sensor_id).update(enriched):
      Zuordnung zu bestehenden Tracks → track_id, color_idx, ghost
7. live_state.update(): speichert alle Tracks (inkl. Ghosts) im Memory
8. database.record_motion(): speichert nur echte (nicht-Ghost) Targets
9. asyncio.run_coroutine_threadsafe → ws_manager.broadcast()
10. Browser aktualisiert SVG-Grundriss in Echtzeit (farbige Punkte + Spuren)
```

---

## Payload-Formate

### ESP32 → Backend (MQTT)

```json
{
  "sensor_id": "radar_wohnzimmer",
  "room_id": "wohnzimmer",
  "timestamp_ms": 1710000000000,
  "target_count": 2,
  "targets": [
    { "id": 1, "x_mm": 420, "y_mm": 2500,
      "speed_mm_s": 120, "distance_mm": 2535, "angle_deg": 9.5 },
    { "id": 2, "x_mm": -300, "y_mm": 1800,
      "speed_mm_s": 0, "distance_mm": 1825, "angle_deg": -9.4 }
  ]
}
```

### Backend → Browser (WebSocket / `GET /api/live`)

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
          "x_mm": 420, "y_mm": 2500,
          "room_x_mm": 1245.3, "room_y_mm": 3102.7,
          "floorplan_x": 142.3, "floorplan_y": 275.1,
          "inside_room": true,
          "zone_id": "sofa",
          "speed_mm_s": 120, "distance_mm": 2535, "angle_deg": 9.5,
          "track_id": 7,
          "color_idx": 0,
          "ghost": false
        }
      ]
    }
  }
}
```

**Felder im Track-Objekt:**

| Feld | Typ | Beschreibung |
|---|---|---|
| `track_id` | int | Stabile, monoton steigende ID; reset bei Service-Neustart |
| `color_idx` | 0/1/2 | Farb-Index: 0=blau, 1=orange, 2=grün |
| `ghost` | bool | `true` = kein aktuelles Signal, letzte bekannte Position |

---

## Thread-Modell

```
Main Thread (asyncio event loop)
  ├── FastAPI HTTP-Handler (async)
  ├── WebSocket-Connections
  └── asyncio.run_coroutine_threadsafe() ← aus MQTT-Thread

MQTT-Thread (paho loop_start)
  └── on_message() → Thread: _process() [daemon]
       ├── coordinate_transform
       ├── tracker.update()
       ├── live_state.update()
       ├── database.record_motion()
       └── run_coroutine_threadsafe(ws_manager.broadcast())

Update-Worker-Thread (daemon, bei POST /api/update/start)
  └── git fetch/reset → pip install → import check → systemctl restart
```

Alle Threads schreiben in `live_state` über Python-GIL + modul-globale Locks (thread-sicher für einfache dict-Zugriffe).

---

## Sicherheitsschichten

1. **SecurityHeadersMiddleware** – CSP, X-Frame-Options, Referrer-Policy
2. **ApiKeyMiddleware** – optionaler `X-API-Key`-Header, `/api/health` ausgenommen
3. **BodySizeLimitMiddleware** – max. 64 KB Request-Body
4. **WebSocket Origin-Check** – `allowed_origins` aus `settings.json`
5. **systemd Sandboxing** – `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`
6. **sudoers** – Nur `systemctl restart hausradar` ohne Passwort erlaubt
