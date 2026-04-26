# HausRadar

Lokales Bewegungserkennungssystem für das Heimnetzwerk.  
ESP32-Boards mit HLK-LD2450 mmWave-Radarsensoren senden Bewegungsdaten per MQTT an einen Raspberry Pi Zero 2 W.  
Eine Webseite zeigt den Hausgrundriss mit Live-Bewegungspunkten, Spuren und Bewegungsprofilen.

---

## Schnellstart

### Voraussetzungen

- Python 3.11 oder neuer
- (Später) Raspberry Pi OS Lite, Mosquitto, ESP32 mit PlatformIO

### Server starten

```bash
cd server
./run.sh
```

Der Server legt beim ersten Start automatisch eine virtuelle Python-Umgebung an und installiert alle Abhängigkeiten.

### Webseite öffnen

```
http://localhost:8000
```

### API-Endpunkte testen

```bash
# System-Status
curl http://localhost:8000/api/health

# Räume
curl http://localhost:8000/api/rooms

# Sensoren
curl http://localhost:8000/api/sensors
```

---

## Verzeichnisstruktur

```
hausradar/
├── config/         Konfigurationsdateien (rooms.json, sensors.json, settings.json)
├── docs/           Dokumentation (Architektur, Hardware, MQTT, Setup)
├── firmware/       ESP32-Firmware (PlatformIO)
├── scripts/        Hilfsskripte (Simulation, Installation, Backup)
├── server/         FastAPI-Backend
│   ├── app/        Python-Quellcode
│   ├── run.sh      Startskript
│   └── requirements.txt
├── tests/          Automatisierte Tests
└── web/            Frontend (HTML/CSS/JavaScript)
```

---

## Konfiguration

Die Konfiguration liegt ausschließlich in JSON-Dateien unter `config/`.  
Beispieldateien mit `*.example.json` zeigen die erwartete Struktur.

| Datei | Inhalt |
|---|---|
| `rooms.json` | Räume mit Abmessungen, Grundriss-Position und Zonen |
| `sensors.json` | Sensoren mit Raumzuordnung und Montageposition |
| `settings.json` | MQTT, Datenbank, WebSocket, Timeouts, Sicherheitseinstellungen |

---

## Sicherer Betrieb (Produktionsmodus)

Vor dem Einsatz auf dem Raspberry Pi die folgenden Einstellungen in `config/settings.json` vornehmen:

```json
{
  "environment": "production",
  "server": {
    "api_key": "ZUFAELLIGER_SCHLUESSEL",
    "allowed_origins": ["http://<Pi-IP>:8000"]
  }
}
```

**Was das bewirkt:**
- `environment: production` → `/api/simulate/motion` gibt 404 zurück (Datenfälschung verhindert)
- `api_key` → Alle API-Anfragen erfordern den Header `X-API-Key` (außer `/api/health`)
- `allowed_origins` → WebSocket-Verbindungen nur von der angegebenen Pi-URL erlaubt

**Weitere Härtungsmaßnahmen** (MQTT-Auth, Firewall, Logrotation, systemd-Sandboxing):  
→ Siehe [`docs/security-hardening.md`](docs/security-hardening.md)

---

## Hardware-Aufbau und Kalibrierung

Schritt-für-Schritt-Anleitung zum Aufbauen, Anschließen, Konfigurieren und Kalibrieren eines Sensors:  
→ Siehe [`docs/hardware-setup.md`](docs/hardware-setup.md)

**Security Audit Report:**  
→ Siehe [`docs/security-audit.md`](docs/security-audit.md) – 4 Critical, 7 High, 7 Medium behoben

---

## Milestones

| # | Thema | Status |
|---|---|---|
| 1 | Minimalversion Backend + Frontend | ✅ |
| 2 | Konfiguration sauber aufbauen | ✅ |
| 3 | Koordinatensystem | ✅ |
| 4 | Simulation ohne Hardware | ✅ |
| 5 | WebSocket Live-Daten | ✅ |
| 6 | SVG-Grundriss | ✅ |
| 7 | Bewegungsspuren | ✅ |
| 8 | SQLite-Datenbank | ✅ |
| 9 | Bewegungsprofile | ✅ |
| 10 | Diagramme im Frontend | ✅ |
| 11 | MQTT einbauen | ✅ |
| 12 | ESP32-Firmware Fake-Daten | ✅ |
| 13 | ESP32-Firmware echter LD2450-Parser | ✅ |
| 14 | Raspberry-Pi-Installation | ✅ |
| 15 | Robustheit | ✅ |
| 16 | Oberfläche polieren | ✅ |
| — | Security Audit + Hardening | ✅ |

---

## Screenshots

*(werden nach Milestone 6 ergänzt)*

---

## Lizenz

Privates Projekt – kein öffentlicher Einsatz vorgesehen.
