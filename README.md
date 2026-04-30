# HausRadar

Lokales Echtzeit-Bewegungserkennungssystem für das Heimnetzwerk.  
ESP32-Boards mit HLK-LD2450 mmWave-Radarsensoren senden Bewegungsdaten per MQTT an einen Raspberry Pi Zero 2 W.  
Eine Webseite zeigt den Hausgrundriss mit Live-Bewegungspunkten, Personentracking, Spuren und Bewegungsprofilen.

> **Kein Bild, keine Kamera, keine Cloud.** Alles läuft lokal im Heimnetzwerk.

---

## Features

| Feature | Beschreibung |
|---|---|
| 📡 **Live-Grundriss** | SVG-Karte mit Räumen, Zonen, Möbeln und Live-Bewegungspunkten |
| 👥 **Personen-Tracking** | Bis zu 3 Personen farblich unterscheidbar (blau/orange/grün) mit stabilen IDs |
| 🔄 **Ghost-Frames** | Kurze Sensor-Aussetzer werden überbrückt – keine springenden Punkte |
| 🗺️ **Bewegungsspuren** | 30-Sekunden-Verlauf pro Person, personenbezogen eingefärbt |
| 📊 **Analyseprofile** | Stundendiagramme, Heatmaps, Zonen- und Raumvergleich |
| 🔧 **Kalibrierung** | Räume und Sensoren per Browser einmessen, Grundriss automatisch berechnen |
| 🏠 **Raumverwaltung** | Räume und Sensoren anlegen, umbenennen, löschen direkt im Browser |
| 📶 **Sensor-Identifikation** | „Identifizieren"-Button: bewegen → Sensor leuchtet auf |
| 🔄 **Web-Update** | Einstellungen → Software-Update: 1-Klick-Update von GitHub mit Rollback |
| 🔐 **Sicherheit** | API-Key, CSP, Origin-Check, Sandboxing (systemd), kein externer Zugriff |

---

## Schnellstart (Entwicklung)

### Voraussetzungen

- Python 3.11 oder neuer
- Git

### Server starten

```bash
git clone https://github.com/monstertobs/hausradar.git
cd hausradar/server
./run.sh
```

Der Server legt beim ersten Start automatisch eine virtuelle Python-Umgebung an
und installiert alle Abhängigkeiten. Webseite: **http://localhost:8000**

### Simulation starten (ohne Hardware)

```bash
source server/.venv/bin/activate
python3 scripts/simulate_sensor_data.py --mqtt --interval 0.3
```

---

## Installation auf Raspberry Pi

Vollständige Anleitung: **[docs/setup-pi-zero-2.md](docs/setup-pi-zero-2.md)**

Kurzversion:

```bash
# 1. Repo klonen
ssh pi@hausradar.local
git clone https://github.com/monstertobs/hausradar.git ~/hausradar

# 2. Installationsskript ausführen (systemd, Mosquitto, venv, sudoers)
cd ~/hausradar && bash scripts/install_pi.sh
```

### Updates einspielen

Im Browser: **Einstellungen → Software-Update → Auf Updates prüfen → Update installieren**

Das Update sichert die Konfiguration, aktualisiert den Code von GitHub,
installiert neue Pakete und startet den Dienst neu. Bei Fehlern automatischer Rollback.

---

## ESP32-Firmware

Anleitung: **[docs/hardware-setup.md](docs/hardware-setup.md)**

```bash
# 1. Zugangsdaten anlegen
cp firmware/esp32-ld2450-mqtt/include/secrets.h.example \
   firmware/esp32-ld2450-mqtt/include/secrets.h
# WLAN-SSID und -Passwort in secrets.h eintragen

# 2. Sensor konfigurieren
# firmware/esp32-ld2450-mqtt/include/config.h anpassen:
#   - MQTT_HOST  → IP-Adresse des Raspberry Pi
#   - SENSOR_ID  → muss zum Eintrag in config/sensors.json passen
#   - ROOM_ID    → Raum-ID aus config/rooms.json

# 3. Flashen
cd firmware/esp32-ld2450-mqtt
pio run -e esp32dev -t upload          # echter LD2450-Sensor
pio run -e esp32dev-sim -t upload      # Walker-Simulation
```

Die korrekte `SENSOR_ID` für jeden ESP32 findest du in der Weboberfläche unter
**Einstellungen → Sensoren** (dort steht das vollständige MQTT-Topic).

---

## Verzeichnisstruktur

```
hausradar/
├── config/                 Konfigurationsdateien (rooms.json, sensors.json, settings.json)
│   ├── rooms.example.json  Beispiel-Raumkonfiguration
│   └── sensors.example.json
├── data/                   SQLite-Datenbank (gitignored)
├── deploy/                 systemd-Service, Mosquitto-Konfiguration, Logrotate
├── docs/                   Dokumentation
│   ├── hardware-setup.md   Hardware-Aufbau und Kalibrierung
│   ├── setup-pi-zero-2.md  Raspberry-Pi-Installation
│   ├── mqtt-topics.md      MQTT-Payload-Format
│   ├── architecture.md     Systemarchitektur
│   ├── coordinate-system.md Koordinatensystem-Erklärung
│   ├── security-hardening.md Sicherheitshärtung
│   └── troubleshooting.md  Fehlerbehebung
├── firmware/
│   └── esp32-ld2450-mqtt/  PlatformIO-Projekt
│       ├── include/
│       │   ├── config.h          Sensor-Konfiguration (anpassen!)
│       │   ├── secrets.h         WLAN-Passwort (gitignored, aus .example erstellen)
│       │   └── secrets.h.example Vorlage
│       └── src/
│           ├── main.cpp          Hauptprogramm
│           └── ld2450.h          LD2450-Parser
├── scripts/
│   ├── install_pi.sh       Erstinstallation auf dem Pi
│   ├── update_pi.sh        Manuelles Update (alternativ zum Web-Update)
│   ├── backup_db.sh        Datenbank-Backup
│   ├── simulate_sensor_data.py  Simulation ohne Hardware
│   └── reset_database.py   Datenbank zurücksetzen
├── server/
│   ├── app/                Python-Quellcode
│   │   ├── main.py         FastAPI-App, Middleware, WebSocket
│   │   ├── config.py       Konfigurationsladen und -validierung
│   │   ├── mqtt_service.py MQTT-Client (paho)
│   │   ├── tracker.py      Personen-Tracker (Nearest-Neighbour)
│   │   ├── coordinate_transform.py  Koordinatenumrechnung
│   │   ├── live_state.py   In-Memory-Zustandsspeicher
│   │   ├── database.py     SQLite-Schicht
│   │   ├── analytics.py    Bewegungsprofile
│   │   ├── version.py      Versionsnummer aus VERSION-Datei
│   │   └── api/            REST-Endpunkte
│   │       ├── rooms.py    Raumverwaltung (CRUD)
│   │       ├── sensors.py  Sensorverwaltung (CRUD)
│   │       ├── calibrate.py  Kalibrierung
│   │       ├── update.py   Web-Update-Manager
│   │       ├── history.py  Bewegungshistorie
│   │       └── profile.py  Analyseprofile
│   ├── requirements.txt
│   └── run.sh              Entwicklungs-Startskript
├── tests/                  Automatisierte Tests (pytest)
├── web/                    Frontend (HTML/CSS/JavaScript)
│   ├── index.html          Live-Grundriss
│   ├── profiles.html       Analyseprofile
│   ├── settings.html       Einstellungen, Sensor-Status, Software-Update
│   ├── calibrate.html      Kalibrierung und Raumverwaltung
│   ├── api.js              API-Client, Version-Badge
│   ├── app.js              Live-Seite Logik
│   ├── floorplan.js        SVG-Grundriss mit Personen-Tracking
│   ├── settings.js         Einstellungsseite
│   ├── calibrate.js        Kalibrierungsseite
│   ├── charts.js           Diagramme (Chart.js)
│   └── styles.css          Globales CSS
└── VERSION                 Aktuelle Versionsnummer
```

---

## Konfiguration

Alle Konfiguration liegt in JSON-Dateien unter `config/`.

| Datei | Inhalt |
|---|---|
| `rooms.json` | Räume mit Abmessungen, Grundriss-Position, Zonen, Möbeln, Türen |
| `sensors.json` | Sensoren mit Raumzuordnung, Position und Montagewinkel |
| `settings.json` | MQTT-Broker, Datenbank, WebSocket, Timeouts, Sicherheit |

---

## API-Endpunkte (Übersicht)

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/api/health` | GET | Systemstatus, Version, Uptime |
| `/api/live` | GET | Aktueller Sensor-Snapshot |
| `/api/rooms` | GET / POST / PATCH / DELETE | Raumverwaltung |
| `/api/sensors` | GET / POST / PATCH / DELETE | Sensorverwaltung |
| `/api/calibrate/…` | GET / POST / PATCH | Kalibrierung |
| `/api/update/status` | GET | Update-Check (GitHub) |
| `/api/update/start` | POST | Update starten |
| `/api/update/stream` | GET | SSE-Fortschrittsstream |
| `/api/history/sessions` | GET | Bewegungshistorie |
| `/api/profile/…` | GET | Analyseprofile |
| `/ws/live` | WebSocket | Live-Datenstrom |

---

## Sicherer Betrieb

Vor dem Produktiveinsatz in `config/settings.json` setzen:

```json
{
  "environment": "production",
  "server": {
    "api_key": "ZUFAELLIGER_SCHLUESSEL",
    "allowed_origins": ["http://<Pi-IP>:8000"]
  }
}
```

Weitere Härtungsmaßnahmen: **[docs/security-hardening.md](docs/security-hardening.md)**

---

## Lizenz

Privates Projekt – kein öffentlicher Einsatz vorgesehen.
