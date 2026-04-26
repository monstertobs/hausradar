# HausRadar – Security-Hardening Guide

**Stand:** 2026-04-26  
**Bezug:** [Security Audit](security-audit.md) Phase 5–7  
**Alle Code-Fixes sind umgesetzt und mit 246 Tests verifiziert.**

---

## Übersicht der umgesetzten Fixes

| ID | Schweregrad | Titel | Status |
|---|---|---|---|
| HR-SEC-001 | Critical | Optionaler X-API-Key für API | ✅ Umgesetzt |
| HR-SEC-002 | Critical | simulate/motion in Production deaktiviert | ✅ Umgesetzt |
| HR-SEC-003 | Critical | MQTT-Authentifizierungs-Hardening | ✅ Konfiguration + Anleitung |
| HR-SEC-004 | Critical | `.gitignore` erstellt | ✅ Umgesetzt |
| HR-SEC-005 | High | HTTP Body-Size-Limit (64 KB) | ✅ Umgesetzt |
| HR-SEC-006 | High | XSS-Schutz via `esc()` in JS | ✅ Umgesetzt |
| HR-SEC-007 | High | Security-HTTP-Header Middleware | ✅ Umgesetzt |
| HR-SEC-008 | High | WebSocket Origin-Prüfung (konfigurierbar) | ✅ Umgesetzt |
| HR-SEC-009 | High | Max. 3 Targets pro Request | ✅ Umgesetzt |
| HR-SEC-010 | High | Starlette CVE-Pins in requirements.txt | ✅ Umgesetzt |
| HR-SEC-011 | Medium | systemd Sandboxing-Optionen | ✅ Umgesetzt |
| HR-SEC-012 | Medium | WebSocket Verbindungslimit | ✅ Umgesetzt |
| HR-SEC-015 | Medium | analytics.py Spaltenname-Whitelist | ✅ Umgesetzt |
| HR-SEC-016 | Medium | Firmware MQTT-Auth-Unterstützung | ✅ Umgesetzt |
| HR-SEC-017 | Low | pytest aus production requirements.txt entfernt | ✅ Umgesetzt |
| HR-SEC-020 | Low | Logrotate-Konfiguration | ✅ Umgesetzt |
| HR-SEC-013 | Medium | HTTP Rate-Limiting | ⬜ Nicht umgesetzt (kein geeignetes Paket für Pi Zero 2 W) |
| HR-SEC-014 | Medium | DB/Backup Dateirechte | ⬜ Deployment-Maßnahme (siehe unten) |
| HR-SEC-018 | Low | Retention 30 Tage reduzieren | ⬜ Empfehlung (user-konfigurierbar) |
| HR-SEC-019 | Low | Besucher-Transparenzhinweis | ⬜ Soziale Maßnahme |
| HR-SEC-021 | Low | python-dotenv CVE | ⬜ Nicht in Produktion installiert |

---

## Deployment-Checkliste (Pi-Installation)

### 1. Produktionsmodus aktivieren

In `config/settings.json`:

```json
{
  "environment": "production"
}
```

→ Deaktiviert `POST /api/simulate/motion` (gibt 404 zurück).

---

### 2. API-Key einrichten (empfohlen)

In `config/settings.json`:

```json
{
  "server": {
    "api_key": "ein-langes-zufaelliges-passwort-hier"
  }
}
```

Alle Browser-Zugriffe auf `/api/*` erfordern dann den Header:
```
X-API-Key: ein-langes-zufaelliges-passwort-hier
```

Ausnahme: `/api/health` ist immer erreichbar (Monitoring).

Einen sicheren Key generieren:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Wichtig:** Der Key wird im Browser in `localStorage` gespeichert. Für maximale Sicherheit zusätzlich Firewall (UFW) verwenden.

---

### 3. MQTT-Authentifizierung einrichten

#### Passwort-Datei erstellen:

```bash
# Benutzer für Backend (lesen)
sudo mosquitto_passwd -c /etc/mosquitto/passwd hausradar-server
# → Passwort eingeben und merken

# Benutzer für Sensoren (schreiben)
sudo mosquitto_passwd /etc/mosquitto/passwd hausradar-sensor
# → Passwort eingeben und merken
```

#### mosquitto-hausradar.conf anpassen:

```ini
allow_anonymous false
password_file /etc/mosquitto/passwd
acl_file /etc/mosquitto/hausradar-acl
```

ACL-Datei kopieren:
```bash
sudo cp deploy/mosquitto-hausradar-acl.example /etc/mosquitto/hausradar-acl
```

#### Backend in settings.json:

```json
{
  "mqtt": {
    "host": "localhost",
    "port": 1883,
    "username": "hausradar-server",
    "password": "dein-server-passwort"
  }
}
```

#### Firmware config.h:

```cpp
#define MQTT_USER     "hausradar-sensor"
#define MQTT_PASSWORD "dein-sensor-passwort"
```

---

### 4. WebSocket Origin-Prüfung aktivieren

In `config/settings.json` (Pi-IP entsprechend anpassen):

```json
{
  "server": {
    "allowed_origins": ["http://192.168.1.100:8000"]
  }
}
```

Mehrere Origins möglich (z.B. IP + Hostname):
```json
"allowed_origins": ["http://192.168.1.100:8000", "http://hausradar.local:8000"]
```

Leer lassen (`[]`) = kein Origin-Check (Entwicklung).

---

### 5. WebSocket Verbindungslimit anpassen

Standard: 20 gleichzeitige WebSocket-Verbindungen.  
In `config/settings.json`:

```json
{
  "server": {
    "ws_max_connections": 10
  }
}
```

---

### 6. Firewall einrichten (UFW)

```bash
# Standardmäßig alles ablehnen
sudo ufw default deny incoming
sudo ufw default allow outgoing

# SSH erlauben (wichtig – sonst Zugriff verloren!)
sudo ufw allow ssh

# HausRadar-Webinterface nur im Heimnetz
sudo ufw allow from 192.168.1.0/24 to any port 8000

# MQTT nur von bekannten Sensor-IPs (optional)
sudo ufw allow from 192.168.1.50 to any port 1883

sudo ufw enable
sudo ufw status
```

---

### 7. DB- und Backup-Dateirechte einschränken

```bash
# Nur der hausradar-User darf die DB lesen
chmod 640 ~/hausradar/data/hausradar.db
chmod 750 ~/hausradar/data/backups/

# Rückwirkend auf alle Backups anwenden
chmod 640 ~/hausradar/data/backups/*.db 2>/dev/null || true
```

---

### 8. Logrotation installieren

```bash
sudo cp deploy/logrotate-hausradar.conf /etc/logrotate.d/hausradar
# Test:
sudo logrotate --debug /etc/logrotate.d/hausradar
```

---

### 9. Starlette-Update nach Upgrade

Nach einem `pip install -r server/requirements.txt` prüfen:

```bash
source server/.venv/bin/activate
pip show starlette | grep Version
# Muss >=0.47.2 sein (Fix für HR-SEC-010)
```

Falls pip-Konflikt mit fastapi:
```bash
pip install "fastapi>=0.116.0" "starlette>=0.47.2"
```

---

## Security-Header Referenz

Folgende Header werden automatisch bei jeder API-Response gesetzt:

| Header | Wert |
|---|---|
| `X-Frame-Options` | `DENY` |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `no-referrer` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'; …` |

---

## Firmware-Secrets sicher verwalten

Die Datei `firmware/esp32-ld2450-mqtt/include/config.h` enthält WLAN-Passwort und MQTT-Credentials. Sie ist in `.gitignore` eingetragen und wird **nicht** committet.

Für mehrere Sensoren empfiehlt sich ein `secrets.h`:

1. Template kopieren:
   ```bash
   cp firmware/esp32-ld2450-mqtt/include/secrets.h.example \
      firmware/esp32-ld2450-mqtt/include/secrets.h
   ```

2. In `config.h` includen statt hardcoden:
   ```cpp
   #include "secrets.h"
   ```

`secrets.h` ist bereits in `.gitignore` eingetragen.

---

## Produktionsmodus – Vollständige settings.json

```json
{
  "environment": "production",
  "mqtt": {
    "host": "localhost",
    "port": 1883,
    "username": "hausradar-server",
    "password": "MQTT_SERVER_PASSWORD",
    "topic": "hausradar/sensor/+/state",
    "reconnect_delay_seconds": 5
  },
  "database": {
    "path": "data/hausradar.db",
    "retention_days": 7,
    "max_writes_per_second_per_sensor": 2
  },
  "websocket": {
    "broadcast_interval_ms": 100
  },
  "live": {
    "sensor_offline_timeout_seconds": 10,
    "recent_activity_timeout_seconds": 30
  },
  "server": {
    "host": "0.0.0.0",
    "port": 8000,
    "api_key": "HIER_ZUFAELLIGEN_KEY_EINTRAGEN",
    "allowed_origins": ["http://192.168.1.100:8000"],
    "body_limit_bytes": 65536,
    "ws_max_connections": 10
  }
}
```
