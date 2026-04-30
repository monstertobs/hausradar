# HausRadar – Fehlerbehebung

> **Hardware-Aufbau und ausführliche Kalibrierung:** [docs/hardware-setup.md](hardware-setup.md)

## Schnell-Diagnose

```bash
# System-Status auf einen Blick
curl -s http://localhost:8000/api/health | python3 -m json.tool

# Live-Zustand aller Sensoren
curl -s http://localhost:8000/api/live | python3 -m json.tool

# Backend-Log (letzte 30 Zeilen)
journalctl -u hausradar -n 30

# MQTT live mithören
mosquitto_sub -h localhost -t "hausradar/#" -v
```

---

## Software-Update schlägt fehl

**Symptom:** Web-Update zeigt Fehler, Service startet danach nicht.

Das Update-System macht automatisch einen Rollback:
1. `git reset --hard <alter Commit>` wird ausgeführt
2. Konfigurationsdateien aus dem Backup wiederhergestellt

**Manueller Rollback:**
```bash
cd ~/hausradar
git log --oneline -5                       # letzten funktionierenden Commit suchen
git reset --hard <commit-hash>
sudo systemctl restart hausradar
```

**sudoers fehlt (Neustart nicht möglich):**
```bash
# Prüfen:
sudo -l | grep hausradar
# Falls fehlend:
SYSTEMCTL=$(which systemctl)
echo "pi ALL=(ALL) NOPASSWD: ${SYSTEMCTL} restart hausradar" | sudo tee /etc/sudoers.d/hausradar
sudo chmod 440 /etc/sudoers.d/hausradar
```

**Update hängt / Stream bricht ab:**
- Browser-Tab schließen und `/api/update/stream` neu laden liefert den aktuellen Status
- Nach Service-Neustart erscheint eine automatische Reload-Meldung

---

## Backend startet nicht

**Symptom:** `systemctl status hausradar` zeigt `failed` oder `active (exited)`.

```bash
journalctl -u hausradar -n 30
```

Häufige Ursachen:

| Fehler im Log | Lösung |
|---|---|
| `Konfigurationsdatei nicht gefunden` | Prüfe ob `config/rooms.json`, `sensors.json`, `settings.json` vorhanden sind |
| `Fehler in rooms.json` | JSON-Syntax prüfen: `python3 -m json.tool config/rooms.json` |
| `ModuleNotFoundError` | Virtualenv neu aufbauen: `bash scripts/install_pi.sh` |
| `Address already in use` | Port 8000 belegt: `sudo lsof -i :8000` → Prozess beenden |

---

## Webseite nicht erreichbar

```bash
# Lokal auf dem Pi testen
curl -s http://localhost:8000/api/health

# Von einem anderen Gerät im Netzwerk
curl -s http://<Pi-IP>:8000/api/health
```

**Backend läuft, aber kein Zugriff von außen:**
- Firewall prüfen: `sudo ufw status`
- Freigeben: `sudo ufw allow 8000/tcp`

**Webseite lädt, aber Daten fehlen:**
- Browser-Konsole öffnen (F12) → Fehlermeldungen prüfen
- WebSocket-Verbindung prüfen: Topbar-Badge sollte „Verbunden" anzeigen

---

## MQTT-Verbindung schlägt fehl

```bash
# Mosquitto-Status prüfen
systemctl status mosquitto

# Mosquitto-Log
cat /var/log/mosquitto/mosquitto.log

# Testverbindung
mosquitto_sub -h localhost -t "hausradar/#" -v
```

**Mosquitto läuft nicht:**
```bash
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
```

**Falsche IP in settings.json:**
```json
"mqtt": { "host": "localhost", "port": 1883 }
```
→ `localhost` verwenden wenn Mosquitto auf demselben Pi läuft.

---

## Sensor sendet keine Daten

### ESP32 – Simulation (SIMULATE-Build)

```bash
# Serial Monitor (PlatformIO)
pio device monitor

# Erwartete Ausgabe:
# [WiFi] Verbunden  IP: 192.168.1.xxx
# [MQTT] Verbunden.
# [SIM] Raum (1234, 2345) mm → Sensor (...)
```

Fehlt die MQTT-Ausgabe: `config.h` prüfen – `MQTT_HOST` auf die Pi-IP setzen.

### ESP32 – Echter LD2450

```bash
pio device monitor
# Erwartete Ausgabe:
# [LD2450] 1 Ziel(e)
```

Keine Ausgabe:
- Verkabelung prüfen: ESP32-GPIO16 → LD2450-TX
- Baudrate: LD2450 sendet immer mit 256000 Baud
- LD2450 braucht ~3 s Aufwärmzeit nach dem Einschalten

### Sensor-Daten im Backend prüfen

```bash
# MQTT-Nachrichten live mithören
mosquitto_sub -h localhost -t "hausradar/sensor/+/state" -v

# Oder: HTTP-Simulation testen
curl -s -X POST http://localhost:8000/api/simulate/motion \
  -H "Content-Type: application/json" \
  -d '{"sensor_id":"radar_wohnzimmer","room_id":"wohnzimmer",
       "timestamp_ms":1710000000000,"target_count":0,"targets":[]}'
```

---

## Sensordaten erscheinen nicht auf der Karte

**Sensor-Status bleibt „offline":**
- `sensor_offline_timeout_seconds` in `config/settings.json` überprüfen (Standard: 10 s)
- Letzte Aktivität: `curl http://localhost:8000/api/live | python3 -m json.tool`

**Ziel-Punkt erscheint außerhalb des Raums:**
- Sensorposition in `config/sensors.json` prüfen (`x_mm`, `y_mm`, `rotation_deg`)

---

## Datenbank-Probleme

**Prüfen:**
```bash
sqlite3 ~/hausradar/data/hausradar.db "PRAGMA integrity_check;"
# Erwartete Ausgabe: ok
```

**„database is locked"-Fehler:**
- Seit M15 läuft SQLite im WAL-Mode – sollte nicht mehr auftreten
- Prüfen ob noch ein alter Prozess läuft: `ps aux | grep uvicorn`

**DB beschädigt – Backup einspielen:**
```bash
ls ~/hausradar/data/backups/
cp ~/hausradar/data/backups/hausradar_DATUM.db ~/hausradar/data/hausradar.db
sudo systemctl restart hausradar
```

**DB zu groß:**
- `retention_days` in `config/settings.json` verringern (Standard: 30)
- Manuell bereinigen: Service neu starten (führt `cleanup_old_data` aus)

---

## Analyse-Seite zeigt keine Daten

Die Diagramme erscheinen erst nach einigen Minuten Sensoraktivität.

```bash
# Anzahl gespeicherter Datensätze prüfen
sqlite3 ~/hausradar/data/hausradar.db \
  "SELECT 'positions' AS t, COUNT(*) FROM target_positions
   UNION SELECT 'sessions', COUNT(*) FROM motion_sessions;"
```

Leere Tabelle obwohl Sensor aktiv: `max_writes_per_second_per_sensor` in `settings.json` erhöhen (Standard: 2).

---

## Simulation starten (ohne echte Sensoren)

```bash
cd ~/hausradar && source server/.venv/bin/activate

# Per HTTP
python3 scripts/simulate_sensor_data.py --interval 0.3

# Per MQTT (realistischer)
python3 scripts/simulate_sensor_data.py --mqtt --interval 0.3
```

---

## Diagnose-Befehle im Überblick

```bash
journalctl -u hausradar -f                          # Backend-Log live
mosquitto_sub -h localhost -t "hausradar/#" -v      # MQTT mithören
curl http://localhost:8000/api/health               # System-Status
curl http://localhost:8000/api/live                 # Live-Zustand aller Sensoren

sqlite3 ~/hausradar/data/hausradar.db \
  "SELECT 'positions' AS t, COUNT(*) FROM target_positions
   UNION SELECT 'sessions', COUNT(*) FROM motion_sessions
   UNION SELECT 'events',   COUNT(*) FROM sensor_events;"
```

---

## Hardware-Probleme

### ESP32 startet nicht

```bash
# Seriellen Monitor öffnen (im Firmware-Verzeichnis):
cd firmware/esp32-ld2450-mqtt
pio device monitor
# Speed: 115200 Baud
```

| Symptom | Mögliche Ursache | Lösung |
|---|---|---|
| Kein Text im Monitor | Schlechtes USB-Kabel | Datenkabel statt Ladekabel verwenden |
| Kein Text im Monitor | Falscher COM-Port | In PlatformIO anderen Port wählen |
| Kein Text im Monitor | Falscher Monitor-Speed | Muss 115200 Baud sein |
| Sofortiger Reset-Loop | Kurzschluss durch Sensor | LD2450 abziehen, neu testen |
| Sofortiger Reset-Loop | Zu schwaches Netzteil | Mind. 1A Netzteil verwenden |

---

### ESP32 verbindet sich nicht mit WLAN

Erwartete Log-Ausgabe:
```
[WiFi] Verbunden  IP: 192.168.178.42
```

| Symptom | Ursache | Lösung |
|---|---|---|
| `[WiFi] Verbindung fehlgeschlagen` | Falsche SSID oder Passwort | `config.h` → `WIFI_SSID` / `WIFI_PASSWORD` prüfen |
| Endloser Verbindungsversuch | 5-GHz-only-Netz | **ESP32 unterstützt nur 2,4 GHz** |
| Verbindung bricht ab | Schwaches Signal | Router näher; WLAN-Repeater; Kanal wechseln |

---

### MQTT verbindet nicht (ESP32-Seite)

Erwartete Log-Ausgabe:
```
[MQTT] Verbunden.
```

| Fehlercode | Bedeutung | Lösung |
|---|---|---|
| `state=-2` | Server nicht erreichbar | Pi-IP in `MQTT_HOST` prüfen: `hostname -I` auf Pi |
| `state=-1` | Verbindung getrennt | Firewall? `sudo ufw allow 1883` auf Pi |
| `state=5` | Auth-Fehler | `MQTT_USER`/`MQTT_PASSWORD` prüfen |
| Verbindet und trennt sofort | Doppelte `MQTT_CLIENT_ID` | Jeder Sensor braucht eindeutige Client-ID |

---

### LD2450 sendet keine Daten

Erwartete Log-Ausgabe wenn jemand vor dem Sensor steht:
```
[LD2450] 1 Ziel(e)
```

| Symptom | Ursache | Lösung |
|---|---|---|
| Dauerhaft `[LD2450] 0 Ziel(e)` | TX/RX-Kabel vertauscht | Sensor-TX↔RX mit ESP32-GPIO tauschen |
| Dauerhaft `[LD2450] 0 Ziel(e)` | Falscher GPIO-Pin | `LD2450_RX_PIN=16` und `LD2450_TX_PIN=17` prüfen |
| Dauerhaft `[LD2450] 0 Ziel(e)` | Sensor ohne Strom | Spannung am VCC mit Multimeter messen |
| Dauerhaft `[LD2450] 0 Ziel(e)` | Aufwärmzeit | 3–5 Sekunden nach Einschalten warten |
| Zufällige Geisterziele | Interferenz (Ventilator, Vorhang, Straße) | Montageort ändern; nicht auf Fenster richten |

Baudrate ist fest: **256000 Baud** – nicht änderbar, nicht falsch konfigurierbar solange `LD2450_BAUD 256000` in config.h steht.

---

### Koordinaten auf der Webseite stimmen nicht

| Symptom | Ursache | Lösung |
|---|---|---|
| Links/rechts gespiegelt | `rotation_deg` falsch | Wert aus Montagetabelle in `docs/coordinate-system.md` prüfen |
| Vorne/hinten gespiegelt | `rotation_deg` um 180° daneben | Wert um 180 erhöhen oder verringern |
| Alles gleichmäßig verschoben | `x_mm`/`y_mm` in sensors.json falsch | Sensorposition neu messen |
| Punkt außerhalb Raumrechteck | `width_mm`/`height_mm` zu klein | Raummaße in rooms.json prüfen |
| Zone nie erkannt | Zonenkoordinaten falsch | Zonengrenzen in rooms.json prüfen |
| `422 Unbekannter Sensor` | `sensor_id` passt nicht zur Config | `SENSOR_ID` in config.h muss exakt `id` in sensors.json entsprechen |

Detaillierte Kalibrierungsanleitung: **[docs/hardware-setup.md → Abschnitt 16](hardware-setup.md)**
