# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Commands

### Backend starten (Entwicklung)

```bash
cd server
./run.sh          # legt .venv an, installiert requirements.txt, startet uvicorn mit --reload
```

Der Server läuft auf `http://localhost:8000`. Die Weboberfläche wird als statische Dateien aus `web/` ausgeliefert.

### Tests ausführen

Tests liegen in `tests/`, der Python-Pfad muss auf `server/` zeigen:

```bash
cd server
source .venv/bin/activate
pip install -r test-requirements.txt   # einmalig: pytest + httpx
cd ..
pytest tests/                          # alle Tests
pytest tests/test_api.py              # einzelne Datei
pytest tests/test_api.py::TestClass::test_name  # einzelner Test
pytest tests/ -x -q                   # bei erstem Fehler stoppen
```

Alle Test-Fixtures sind in den jeweiligen Test-Dateien definiert (kein `conftest.py`). Tests benutzen `FastAPI.TestClient` und manipulieren `app.state` direkt.

### Firmware (ESP32)

```bash
cd firmware/esp32-ld2450-mqtt
pio run -e esp32dev -t upload          # echter LD2450-Sensor
pio run -e esp32dev-sim -t upload      # Walker-Simulation ohne Sensor
pio device monitor                     # serieller Monitor (115200 Baud)
```

### Simulation ohne Hardware

```bash
source server/.venv/bin/activate
python3 scripts/simulate_sensor_data.py --mqtt --interval 0.3
```

---

## Architektur

### Überblick

```
HLK-LD2450 → ESP32 → MQTT → FastAPI Backend → SQLite
                                     │
                              WebSocket Broadcast
                                     │
                               Browser (web/)
```

Das Backend ist ein **einzelner FastAPI-Prozess** auf dem Raspberry Pi Zero 2 W. Kein async Datenbank-Treiber, kein ORM – reines `sqlite3` mit `contextmanager get_db()`.

### Konfiguration (`config/`)

Alle Konfiguration liegt in drei JSON-Dateien, die beim Start einmalig in `app.state` geladen werden:
- `rooms.json` – Räume mit Abmessungen, Grundriss-Pixelposition (`floorplan`), Zonen
- `sensors.json` – Sensoren mit Raumzuordnung, Position (`x_mm`/`y_mm`), `rotation_deg`
- `settings.json` – MQTT-Broker, Datenbank-Pfad, WebSocket-Intervall, Timeouts, `server.api_key`

`config.py` validiert diese Dateien beim Laden und wirft `RuntimeError` bei Fehlern – der Server startet dann gar nicht.

### MQTT → Live-State → WebSocket

Das ist der kritische Datenpfad:

1. `mqtt_service.py` (`MqttService`) – paho-mqtt läuft in einem **eigenen Thread** via `loop_start()`. Jede eingehende Nachricht spawnt einen weiteren `threading.Thread` für `_process()`.
2. `_process()` ruft `coordinate_transform.full_transform()` auf, schreibt in `live_state` und in SQLite, dann `asyncio.run_coroutine_threadsafe()` für den WebSocket-Broadcast.
3. `live_state.py` – einfaches modul-globales dict `_state`, thread-sicher via GIL.
4. `websocket_service.py` (`ConnectionManager`) – hält Liste aller offenen WS-Verbindungen, broadcastet `live_state.build_response()`.

Sensor-Offline-Erkennung erfolgt **nicht über MQTT-LWT**, sondern über das Timeout `settings.live.sensor_offline_timeout_seconds` in `build_response()`.

### Koordinatensystem (`coordinate_transform.py`)

Drei Räume: Sensor-Koordinaten → Raum-Koordinaten → SVG-Pixel.

Formel (Uhrzeigersinn, `θ = rotation_deg`):
```
x_raum = sensor.x_mm + xs·cos(θ) + ys·sin(θ)
y_raum = sensor.y_mm − xs·sin(θ) + ys·cos(θ)
```

| `rotation_deg` | Sensor zeigt in |
|:---:|---|
| 0° | Raum-+y (Montage an y=0-Wand, Standard) |
| 90° | Raum-+x (Montage an x=0-Wand) |
| 180° | Raum-−y |
| 270° | Raum-−x |

### Security-Middleware (`main.py`)

Drei `BaseHTTPMiddleware`-Klassen in dieser Reihenfolge (äußerste zuerst registriert):

1. `SecurityHeadersMiddleware` – setzt CSP, X-Frame-Options, etc. auf jede Response
2. `ApiKeyMiddleware` – prüft `X-API-Key`-Header wenn `settings.server.api_key` gesetzt; `/api/health` ist ausgenommen
3. `BodySizeLimitMiddleware` – prüft nur `Content-Length`-Header (liest keinen Stream)

**Wichtig:** `BaseHTTPMiddleware` darf den Request-Body **nicht lesen** (kein `request.stream()`), da das `_stream_consumed=True` setzt und FastAPI den Body danach nicht mehr lesen kann.

Globale Variable `_API_KEY` (Modulebene) wird im Lifespan gesetzt und in Tests direkt manipuliert.

### Datenbankschicht (`database.py`)

- WAL-Mode + `synchronous=NORMAL` für den Pi Zero 2 W
- Rate-Limiting per Sensor: `_rate_ok()` verhindert zu häufige Schreibzugriffe (konfigurierbar via `database.max_writes_per_second_per_sensor`)
- Session-Tracking: `_room_sessions` (Modulebene) hält offene `motion_sessions`; wird beim Server-Start automatisch bereinigt
- Für Tests: `db._reset_for_tests()` leert Rate-Limiter und Session-Cache; `db._clear_tables_for_tests(path)` leert DB-Inhalte

### Personen-Tracker (`tracker.py`)

Sitzt zwischen `coordinate_transform` und `live_state`:

1. `mqtt_service._process()` baut `enriched`-Liste aus Koordinatenumrechnung
2. `tracker.get_tracker(sensor_id).update(enriched)` → fügt `track_id`, `color_idx`, `ghost` hinzu
3. `ghost=True` bedeutet: kein aktuelles Messsignal, letzte bekannte Position wird für max. `MAX_MISS_FRAMES=4` Frames gehalten

Algorithmus: Greedy Nearest-Neighbour mit `MAX_ASSIGN_DIST_MM=800`. Jeder Track bekommt einen Farb-Index (0=blau, 1=orange, 2=grün), der bis zur Track-Löschung stabil bleibt.

### Versionsmanagement

- `VERSION` (Repo-Root) – einzige Quelle der Versionsnummer
- `server/app/version.py` liest die Datei beim Import → `__version__`
- FastAPI-App-Version, `/api/health` und die Version-Badge in der Weboberfläche nutzen alle `__version__`
- Releases: `git tag vX.Y.Z && git push origin vX.Y.Z && gh release create vX.Y.Z`

### Web-Update-Manager (`api/update.py`)

Ablauf:
1. `POST /api/update/start` startet `_worker()` in Daemon-Thread
2. `GET /api/update/stream` streamt SSE-Log-Einträge (polling alle 0,35 s)
3. Worker: git fetch → git reset --hard origin/main → config-Restore → pip install → import-Check → `sudo systemctl restart hausradar`
4. `sudo systemctl restart` killt den Prozess; Browser erkennt Verbindungsabbruch und pollt `/api/health` bis der neue Prozess antwortet
5. Rollback bei Fehler in Schritt pip/import: `git reset --hard <prev_commit>` + config-Restore

sudoers-Eintrag nötig: `pi ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart hausradar`

### Frontend (`web/`)

Vanilla JS, kein Framework. Vier Seiten:
- `index.html` + `app.js` + `floorplan.js` – Live-Grundriss mit SVG, WebSocket, Personen-Tracking
- `room.html` – Einzelraum-Ansicht
- `profiles.html` + `charts.js` – Analyse-Diagramme (Chart.js aus CDN)
- `settings.html` + `settings.js` – Konfiguration, Sensor-Status, Sensor-Identifikation, Software-Update
- `calibrate.html` + `calibrate.js` – Kalibrierung, Raumverwaltung, Auto-Layout

`api.js` enthält `esc()` (HTML-Escaping) – **alle** von der API kommenden Strings in `innerHTML`-Templates müssen durch `esc()`.

`api.js` injiziert beim Laden jeder Seite eine Version-Badge in `.logo` via `GET /api/health`.

### API-Endpunkte

| Prefix | Router | Datei |
|---|---|---|
| `/api/rooms` | `rooms.router` | `api/rooms.py` |
| `/api/sensors` | `sensors.router` | `api/sensors.py` |
| `/api/calibrate` | `calibrate.router` | `api/calibrate.py` |
| `/api/update` | `update.router` | `api/update.py` |
| `/api/simulate/motion` | `motion.router` | `api/motion.py` |
| `/api/history` | `history.router` | `api/history.py` |
| `/api/profile` | `profile.router` | `api/profile.py` |
| `/api/health` | inline in `main.py` | — |
| `/api/live` | inline in `main.py` | — |
| `/ws/live` | WebSocket in `main.py` | — |

`POST /api/simulate/motion` gibt 404 zurück wenn `settings.environment == "production"`.

Neue CRUD-Endpunkte:
- `PATCH /api/rooms/{id}` – Raum umbenennen
- `POST /api/rooms` – neuen Raum anlegen
- `DELETE /api/rooms/{id}` – Raum + Sensoren löschen
- `PATCH /api/sensors/{id}` – Sensor bearbeiten
- `POST /api/sensors` – neuen Sensor anlegen
- `DELETE /api/sensors/{id}` – Sensor löschen
- `PATCH /api/calibrate/room/{id}` – Raummaße bearbeiten
- `PATCH /api/calibrate/sensor/{id}` – Sensorwerte bearbeiten
- `POST /api/calibrate/layout` – Auto-Layout (BFS)

### Deployment

- systemd-Service: `deploy/hausradar.service` → `sudo systemctl restart hausradar`
- `run.sh` verwendet `--reload --log-level info` (Entwicklung); der systemd-Service verwendet `--log-level warning` ohne `--reload`
- Sandboxing: `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome=read-only`
- MQTT-Broker: Mosquitto lokal auf dem Pi, Konfig in `deploy/mosquitto-hausradar.conf`

### ESP32-Firmware (`firmware/esp32-ld2450-mqtt/`)

- Alle Konfiguration in `include/config.h` (durch `.gitignore` geschützt)
- Zwei Build-Flags: ohne `-DSIMULATE` = echter LD2450-Parser; mit `-DSIMULATE` = Walker-Simulation
- UART2: GPIO16 = RX (empfängt LD2450-TX), GPIO17 = TX; 256000 Baud fest
- JSON-Payload mit `ArduinoJson`, MQTT mit `PubSubClient`
