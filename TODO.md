# HausRadar – Aufgabenliste

## Milestone 1 – Minimalversion ✅
- [x] Projektstruktur anlegen
- [x] FastAPI-Backend mit /api/health, /api/rooms, /api/sensors
- [x] config/rooms.json mit 5 Räumen
- [x] config/sensors.json mit 5 Sensoren
- [x] config/settings.json
- [x] Frontend: index.html, styles.css, app.js, api.js
- [x] server/run.sh (venv + uvicorn)
- [x] server/requirements.txt
- [x] README.md mit Startanleitung

## Milestone 2 – Konfiguration
- [ ] Validierung: Sensoren referenzieren existierende room_id
- [ ] Validierung: Raumgrößen positiv
- [ ] Warnung wenn Sensor außerhalb des Raums
- [ ] Verständliche Fehlermeldungen bei ungültigem JSON

## Milestone 3 – Koordinatensystem
- [ ] coordinate_transform.py implementieren
- [ ] transform_sensor_to_room()
- [ ] transform_room_to_floorplan()
- [ ] is_target_inside_room()
- [ ] detect_zone()
- [ ] Tests für alle Rotationen und Randfälle
- [ ] docs/coordinate-system.md (Deutsch)

## Milestone 4 – Simulation
- [ ] scripts/simulate_sensor_data.py
- [ ] POST /api/simulate/motion
- [ ] GET /api/live
- [ ] Koordinatenumrechnung in Endpunkt integrieren

## Milestone 5 – WebSocket
- [ ] /ws/live Endpunkt
- [ ] Broadcast bei neuen Bewegungsdaten
- [ ] Frontend: WebSocket-Verbindung
- [ ] Frontend: Verbindungsstatus anzeigen
- [ ] Frontend: Auto-Reconnect alle 2 Sekunden
- [ ] Frontend: Debug-JSON der letzten Daten

## Milestone 6 – SVG-Grundriss
- [ ] web/floorplan.js
- [ ] Räume als SVG-Rechtecke
- [ ] Raumnamen einzeichnen
- [ ] Zonen darstellen
- [ ] Sensorpositionen markieren
- [ ] Live-Zielpunkte aus WebSocket
- [ ] Raumstatus farblich (idle/recent/active/offline)

## Milestone 7 – Bewegungsspuren
- [ ] Spurpuffer pro Sensor/Target (30 Sekunden)
- [ ] SVG polyline für Spuren
- [ ] Alte Punkte entfernen
- [ ] Offline-Erkennung (> 10 s keine Daten)
- [ ] Performance für iPhone sicherstellen

## Milestone 8 – SQLite
- [ ] server/app/database.py
- [ ] Tabellen: sensor_events, target_positions, motion_sessions
- [ ] GET /api/history/latest
- [ ] GET /api/history?room_id=&hours=
- [ ] Schreibfehler abfangen

## Milestone 9 – Bewegungsprofile
- [ ] server/app/analytics.py
- [ ] GET /api/profile/hourly
- [ ] GET /api/profile/heatmap
- [ ] GET /api/profile/zones
- [ ] GET /api/profile/rooms
- [ ] Tests für alle Analytics-Funktionen

## Milestone 10 – Diagramme
- [ ] web/charts.js
- [ ] Stunden-Balkendiagramm
- [ ] Raumvergleich
- [ ] Zonenaktivität
- [ ] 7×24 Heatmap (HTML/CSS Grid)
- [ ] Letzte Bewegungssitzungen

## Milestone 11 – MQTT
- [ ] server/app/mqtt_service.py
- [ ] paho-mqtt integrieren
- [ ] Subscribe auf hausradar/sensor/+/state
- [ ] MQTT-Reconnect
- [ ] /api/health um mqtt_connected erweitern
- [ ] Simulation optional per MQTT senden

## Milestone 12 – ESP32 Firmware (Fake)
- [ ] firmware/esp32-ld2450-mqtt/platformio.ini
- [ ] firmware/esp32-ld2450-mqtt/src/main.cpp
- [ ] WLAN + MQTT verbinden
- [ ] Fake-Targets alle 500 ms senden
- [ ] Availability-Topic senden
- [ ] WLAN/MQTT-Reconnect

## Milestone 13 – ESP32 echter LD2450-Parser
- [ ] firmware/.../ld2450_parser.cpp + .h
- [ ] UART2 auf GPIO16/17 @ 256000 Baud
- [ ] Frame-Parser für bis zu 3 Targets
- [ ] Raw-Frame-Debug-Modus
- [ ] docs/hardware.md aktualisieren

## Milestone 14 – Raspberry Pi Installation
- [ ] scripts/install_pi.sh
- [ ] server/hausradar.service
- [ ] scripts/backup_db.sh
- [ ] docs/setup-pi-zero-2.md

## Milestone 15 – Robustheit
- [ ] Sensor-Offline nach 15 s
- [ ] DB-Schreibrate begrenzen (max. 2/s pro Sensor)
- [ ] Ungültige Koordinaten filtern
- [ ] Frontend-Warnungen für MQTT/Sensor/DB
- [ ] /api/health: uptime, db_ok, mqtt_connected
- [ ] Alte Rohdaten automatisch bereinigen

## Milestone 16 – Oberfläche
- [ ] Dunkles Dashboard-Design finalisieren
- [ ] Mobile optimieren
- [ ] Legende hinzufügen
- [ ] Detailbereich für ausgewählten Raum
- [ ] README Screenshots-Platzhalter
- [ ] docs/troubleshooting.md erweitern
