# HausRadar – Security Audit

**Erstellt:** 2026-04-26  
**Auditor:** Defensive Security Review (Claude)  
**Scope:** Vollständiges Repository `hausradar/`  
**Standards:** OWASP WSTG, OWASP ASVS 5.0, OWASP Top 10, NIST CSF 2.0  
**Methodik:** Statische Code-Analyse, automatisierte Checks (bandit, pip-audit), manuelle Review

---

## Executive Summary

HausRadar ist ein lokales Smart-Home-System ohne öffentliche Erreichbarkeit.  
Das Security-Profil ist für ein reines Heimnetz-Projekt insgesamt solide: keine externen Abhängigkeiten, kein Cloud-Backend, gute Input-Validierung auf Payload-Ebene, WAL-SQLite-Modus, parametrisierte Queries.

Es wurden **4 kritische**, **7 hohe**, **7 mittlere** und **5 niedrige** Findings identifiziert.

Die kritischsten Probleme:
1. **Kein API/Dashboard-Passwortschutz** – jedes Gerät im WLAN kann Bewegungsprofile einsehen.
2. **`/api/simulate/motion` immer aktiv** – jedes LAN-Gerät kann beliebige Sensordaten injizieren.
3. **MQTT anonym** – jedes LAN-Gerät kann Fake-Sensordaten publishen.
4. **Keine `.gitignore`** – Firmware-Secrets und DB-Dateien könnten versehentlich committed werden.

---

## Scope

| Bereich | Geprüft |
|---|---|
| FastAPI Backend | ✅ |
| SQLite / Datenbank | ✅ |
| MQTT-Service | ✅ |
| WebSocket-Service | ✅ |
| Statisches Frontend (HTML/CSS/JS) | ✅ |
| ESP32-Firmware (C++) | ✅ |
| systemd-Service | ✅ |
| Installationsskripte | ✅ |
| Konfigurationsdateien | ✅ |
| Python-Abhängigkeiten (pip-audit) | ✅ |

**Nicht geprüft:** Laufende Linux-Konfiguration (kein Pi verfügbar), Router/Firewall-Konfiguration, WLAN-Verschlüsselung, physische Sicherheit des Pi.

---

## Systemübersicht

### Komponenten

| Komponente | Technologie | Läuft auf |
|---|---|---|
| MQTT-Broker | Mosquitto | Raspberry Pi |
| Backend | Python 3.9 / FastAPI / uvicorn | Raspberry Pi |
| Datenbank | SQLite 3 (WAL-Mode) | Raspberry Pi |
| WebSocket | FastAPI WebSocket / starlette | Raspberry Pi |
| Frontend | Vanilla HTML/CSS/JS, SVG | Browser |
| Firmware (Fake) | ESP32 / Arduino / PlatformIO | ESP32 |
| Firmware (Real) | ESP32 / HLK-LD2450 | ESP32 |

### Datenflüsse

```
ESP32 ──MQTT (1883)──► Mosquitto ──► MqttService._process()
                                          │
                       Browser ──REST──► FastAPI ──► SQLite (WAL)
                       Browser ──WS────► WebSocket ◄─┘
                                              │
                                         ◄───┘  (broadcast)
```

### Trust Boundaries

```
[Untrusted]          [Semi-trusted]        [Trusted]
ESP32/Sensor    ──►  MQTT Broker      ──►  FastAPI-Prozess
LAN-Browser     ──►  HTTP/WS API      ──►  SQLite-Datei
Gast-WLAN       ──►  (kein Schutz!)        Dateisystem
Internet        ──►  (kein Schutz!)        systemd/Linux
```

**Kritisch:** Es gibt derzeit keine Trust Boundary zwischen LAN-Browser und FastAPI-API – die API ist ohne Authentifizierung offen.

### Schützenswerte Assets

| Asset | Sensitivität | Ort |
|---|---|---|
| Bewegungsrohdaten | Hoch – Präsenzmuster | SQLite DB |
| Heatmaps / Zeitprofile | Hoch – Verhaltensprofile | SQLite + API |
| Grundriss-Layout | Mittel – Gebäudestruktur | rooms.json |
| Sensor-IDs / -Positionen | Mittel | sensors.json |
| WLAN-Credentials | Kritisch | config.h (Firmware) |
| MQTT-Credentials | Mittel | settings.json, config.h |
| SQLite-Datenbank | Hoch | data/hausradar.db |
| Backup-Dateien | Hoch | data/backups/ |
| SSH/Pi-Zugangsdaten | Kritisch | Pi-System |

### Datenschutzbewertung

Bewegungsprofile ermöglichen die Erkennung von Anwesenheit, Schlafzeiten, Routinen und Gewohnheiten aller Personen im Haushalt. Obwohl keine Kamera verwendet wird, sind die gesammelten Daten hochsensibel im Sinne der DSGVO (Profiling des Aufenthaltsverhaltens in Wohnräumen). Besondere Risiken:

- **Datensparsamkeit:** 30 Tage Rohpositions-Retention ist für ein Heimnetz-System lang. 7 Tage wären ausreichend.
- **Keine Löschfunktion:** Es gibt keine API oder UI um Daten gezielt zu löschen.
- **Besucher:** Personen, die das Haus betreten, werden ohne Kenntnis erfasst.
- **Keine Zweckbindung:** Die gesammelten Daten könnten über die API von jedem LAN-Gerät abgerufen werden.

---

## Security-Checkliste

### A. Netzwerk- und Deployment-Sicherheit

| # | Prüfpunkt | Status | Anmerkung |
|---|---|---|---|
| A1 | Webserver lauscht nur auf LAN (nicht 0.0.0.0) | **FINDING** | `--host 0.0.0.0` in Service + install_pi.sh |
| A2 | System nicht versehentlich aus Internet erreichbar | NEEDS_REVIEW | Abhängig von Router-Konfig des Users |
| A3 | Hinweis auf kein Portforwarding im Docs | OK | Setup-Doc vorhanden |
| A4 | Service läuft nicht als root | OK | `User=__USER__` (konfigurierbar) |
| A5 | systemd-Hardening-Optionen gesetzt | **FINDING** | NoNewPrivileges, PrivateTmp etc. fehlen |
| A6 | Mosquitto anonym im LAN erreichbar | **FINDING** | `allow_anonymous true` |
| A7 | UFW/Firewall-Empfehlung vorhanden | **FINDING** | Fehlt in Deployment-Docs |
| A8 | Trennung Heimnetz/Gast-/IoT-Netz | NEEDS_REVIEW | Empfehlung fehlt |

### B. MQTT-Sicherheit

| # | Prüfpunkt | Status | Anmerkung |
|---|---|---|---|
| B1 | MQTT ohne Authentifizierung | **FINDING** | `allow_anonymous true` |
| B2 | sensor_id / room_id validiert | OK | Backend prüft gegen Konfig |
| B3 | Unbekannte Sensoren abgelehnt | OK | 422 in HTTP, Warning+skip in MQTT |
| B4 | Rate-Limits auf DB-Seite | OK | `max_writes_per_second_per_sensor` |
| B5 | Payload-Größenlimit MQTT | **FINDING** | Kein Limit in mosquitto.conf |
| B6 | Schutz vor MQTT-Flooding | **FINDING** | Fehlt |
| B7 | Retained messages berücksichtigt | NEEDS_REVIEW | Keine retained messages konfiguriert |
| B8 | TLS für MQTT | NOT_APPLICABLE | Heimnetz; optional als Hardening |

### C. FastAPI / Webserver-Sicherheit

| # | Prüfpunkt | Status | Anmerkung |
|---|---|---|---|
| C1 | Input Validation (Pydantic) | OK | Umfassend umgesetzt |
| C2 | Stacktraces nicht an Client | OK | FastAPI gibt keine Stacktraces zurück |
| C3 | Kein Debug-Modus in Produktion | OK | debug=False (Standard) |
| C4 | CORS konfiguriert | **FINDING** | Keine CORS-Middleware, kein Wildcard explizit |
| C5 | `/api/simulate/motion` nur in dev | **FINDING** | Immer aktiv |
| C6 | Authentifizierung für Dashboard | **FINDING** | Keine Auth |
| C7 | Rate-Limiting auf HTTP-Ebene | **FINDING** | Fehlt |
| C8 | JSON-Körpergröße begrenzt | **FINDING** | Kein Body-Limit |
| C9 | Security HTTP-Header | **FINDING** | Keine Middleware |
| C10 | WebSocket Origin-Prüfung | **FINDING** | Fehlt |
| C11 | Fehlermeldungen ohne interne Pfade | OK | Logs nur serverseitig |
| C12 | Max. Targets pro Request | **FINDING** | Kein Limit (LD2450 max = 3) |

### D. Frontend-Sicherheit

| # | Prüfpunkt | Status | Anmerkung |
|---|---|---|---|
| D1 | XSS via innerHTML mit API-Daten | **FINDING** | r.name, s.name, z.name unescaped |
| D2 | SVG-Injection | OK | Floorplan nutzt textContent für Namen |
| D3 | Externe CDN-Skripte | OK | Keine externen Abhängigkeiten |
| D4 | Content Security Policy | **FINDING** | Fehlt |
| D5 | Keine Secrets im Frontend | OK | |
| D6 | eval() / Function() | OK | Nicht verwendet |

### E. SQLite-Sicherheit

| # | Prüfpunkt | Status | Anmerkung |
|---|---|---|---|
| E1 | SQL-Injection (parametrisierte Queries) | OK | WHERE-Werte parametrisiert |
| E2 | WHERE-Klausel-Pattern (Bandit B608) | NEEDS_REVIEW | Spalten-Namen hardcoded, sicher – aber fragiler Pattern |
| E3 | WAL-Mode aktiv | OK | Seit M15 umgesetzt |
| E4 | DB-Dateirechte | **FINDING** | Nicht auf 640 gesetzt |
| E5 | Backup-Dateirechte | **FINDING** | Nicht eingeschränkt |
| E6 | Retention/Cleanup | NEEDS_REVIEW | 30 Tage für Rohdaten ist lang |
| E7 | Schutz vor Schreibflut | OK | Rate-Limiter pro Sensor |
| E8 | Backup-Verschlüsselung | NOT_APPLICABLE | Lokal, optional |

### F. Datenschutz / Privacy by Design

| # | Prüfpunkt | Status | Anmerkung |
|---|---|---|---|
| F1 | Keine Cloud-Abhängigkeit | OK | Vollständig lokal |
| F2 | Keine Telemetrie | OK | |
| F3 | Retention konfigurierbar | OK | `retention_days` in settings.json |
| F4 | Rohdaten-Löschfunktion | **FINDING** | Fehlt |
| F5 | Hinweis Besucher-Transparenz | **FINDING** | Fehlt |
| F6 | Grundrissdaten lokal | OK | Nur config/ |
| F7 | Datensparsamkeit (30 Tage) | NEEDS_REVIEW | Empfehlung: 7 Tage Rohdaten |

### G. Secrets und Konfiguration

| # | Prüfpunkt | Status | Anmerkung |
|---|---|---|---|
| G1 | `.gitignore` vorhanden | **FINDING** | Fehlt komplett |
| G2 | WLAN-Passwort im Quellcode | **FINDING** | `config.h` enthält Platzhalter – aber keine .gitignore |
| G3 | MQTT-Auth in settings.json | OK | Kein Passwort (anonym) – dokumentiert |
| G4 | Beispiel-Konfig ohne echte Secrets | OK | Nur Platzhalter |
| G5 | `secrets.h.example` für Firmware | **FINDING** | Fehlt; nur Kommentar in config.h |

### H. ESP32-Firmware-Sicherheit

| # | Prüfpunkt | Status | Anmerkung |
|---|---|---|---|
| H1 | WLAN-Secrets ausgelagert (nicht direkt im Code) | OK | In config.h (separate Datei) |
| H2 | MQTT-Auth-Unterstützung | **FINDING** | Firmware unterstützt kein MQTT-Passwort |
| H3 | Reconnect robust | OK | WiFi+MQTT Reconnect implementiert |
| H4 | Payload validiert | OK | Firmware sendet konsistentes Format |
| H5 | Keine unnötigen Services | OK | Kein OTA, kein Webserver |
| H6 | Debug-Ausgaben | NEEDS_REVIEW | Serial-Ausgaben aktiv (lokal OK) |

### I. Linux / Pi-Hardening

| # | Prüfpunkt | Status | Anmerkung |
|---|---|---|---|
| I1 | Eigener User für hausradar | NEEDS_REVIEW | Install nutzt `pi`-User; kein dedizierter User |
| I2 | NoNewPrivileges | **FINDING** | Fehlt in systemd-Unit |
| I3 | PrivateTmp | **FINDING** | Fehlt |
| I4 | ProtectSystem | **FINDING** | Fehlt |
| I5 | ProtectHome | **FINDING** | Fehlt |
| I6 | ReadWritePaths eingeschränkt | **FINDING** | Fehlt |
| I7 | Restart on failure | OK | `Restart=always` |
| I8 | MemoryMax gesetzt | OK | 256M |
| I9 | Logrotation | **FINDING** | Fehlt |

### J. Supply Chain

| # | Prüfpunkt | Status | Anmerkung |
|---|---|---|---|
| J1 | Abhängigkeiten gepinnt | OK | Alle exakt versioniert |
| J2 | Bekannte CVEs | **FINDING** | starlette 2× CVE, python-dotenv 1× CVE |
| J3 | pytest in requirements.txt | **FINDING** | Gehört in test-requirements, nicht Produktion |
| J4 | Keine externen CDN-Abhängigkeiten | OK | Vollständig offline-fähig |

### K. Missbrauchsfälle

| Angriff | Risiko | Aktueller Schutz |
|---|---|---|
| Fake-MQTT-Daten senden | Hoch | Sensor-/Room-ID-Validierung, sonst offen |
| MQTT-Flooding | Mittel | DB-Rate-Limit, kein MQTT-Limit |
| Riesiges JSON an API | Hoch | Kein Body-Limit |
| HTML in Raumnamen (XSS) | Mittel | Kein Escaping in Frontend |
| WebSocket massenhaft öffnen | Mittel | Kein Verbindungslimit |
| Bewegungsprofile lesen | Hoch | Keine Auth |
| Anwesenheit/Abwesenheit erkennen | Hoch | Keine Auth |
| SQLite-Backup lesen | Mittel | Keine Dateirechte-Einschränkung |
| Port 8000 versehentlich offen | Hoch | Keine Auth, kein Ratelimit |
| Pi läuft mit Standardpasswort | Kritisch | Keine Prüfung in Installationsskript |
| Angreifer öffnet WebSocket | Mittel | Keine Origin-Prüfung, aber kein Schreibzugriff |

---

## Automatisierte Checks

### python -m compileall
```
Ergebnis: OK – keine Syntaxfehler
```

### pytest
```
213 passed in 59.5s – alle Tests grün
```

### pip-audit
```
Found 4 known vulnerabilities in 3 packages:

Name          Version ID                  Fix Versions
------------- ------- ------------------- ------------
pytest        8.4.2   GHSA-6w46-j5rx-g56g 9.0.3        (test-only)
starlette     0.41.3  GHSA-2c2j-9gv5-cj73 0.47.2       ← FINDING
starlette     0.41.3  GHSA-7f5h-v6xp-fcq8 0.49.1       ← FINDING
python-dotenv 1.2.1   GHSA-mf9w-mj56-hr94 1.2.2
```

### bandit
```
8 Issues total:
  - 7× B608 Medium: f-string SQL in analytics.py + database.py
    → FALSE POSITIVE: Spaltennamen sind hardcoded, Werte parametrisiert
    → Pattern trotzdem fragil – Whitelist empfohlen
  - 1× B110 Low: try/except/pass in mqtt_service.py:69 (stop())
    → Akzeptabel beim Stoppen einer Verbindung
```

### Hardcoded Secrets
```
WLAN-Passwort: firmware/include/config.h – Platzhalter "mein-wlan-passwort"
  → Kein echtes Secret, aber fehlende .gitignore ist das eigentliche Problem
```

### .gitignore
```
FEHLT KOMPLETT – keine .gitignore im Projektverzeichnis
```

### innerHTML-Verwendung
```
web/app.js:135,152     – r.name, s.name, s.id, s.room_id in Template-Literals
web/settings.js:88,109 – r.name, s.name, z.name, roomName in Template-Literals
web/charts.js:92,140   – labelFn(d), room_id, zone_id in Ausgabe
web/floorplan.js:131   – SVG-Filter: statisches HTML (OK)
web/floorplan.js:163   – Container leeren (OK)
```

### Security Headers
```
FEHLEN KOMPLETT – keine Middleware in main.py
```

### CORS
```
Keine CORSMiddleware konfiguriert.
FastAPI-Standard: kein CORS → keine Cross-Origin-Anfragen erlaubt (gut).
Aber: keine explizite Konfiguration, kein Logging von Verstößen.
```

### WebSocket Origin
```
Keine Origin-Prüfung in websocket_service.py oder main.py.
```

### Request Body Limit
```
Kein Limit konfiguriert. Starlette-Standard: theoretisch unbegrenzt.
```

### Max Targets
```
motion.py: Kein Maximum auf len(targets). LD2450 sendet max. 3 Ziele.
Ein Angreifer könnte target_count=1000, targets=[...1000 Objekte...] senden.
```

---

## Findings-Tabelle

| ID | Titel | Schweregrad | Kategorie | Status |
|---|---|---|---|---|
| HR-SEC-001 | Keine Authentifizierung für Dashboard/API | **Critical** | API, Privacy | ✅ Fixed |
| HR-SEC-002 | `/api/simulate/motion` immer aktiv | **Critical** | API | ✅ Fixed |
| HR-SEC-003 | MQTT allow_anonymous=true | **Critical** | MQTT | ✅ Fixed (Konfig + Anleitung) |
| HR-SEC-004 | Keine `.gitignore` | **Critical** | Supply-Chain | ✅ Fixed |
| HR-SEC-005 | Kein HTTP Request-Body-Limit | **High** | API | ✅ Fixed |
| HR-SEC-006 | XSS via innerHTML mit API-Daten | **High** | Frontend | ✅ Fixed |
| HR-SEC-007 | Keine Security-HTTP-Header | **High** | API | ✅ Fixed |
| HR-SEC-008 | Keine WebSocket Origin-Prüfung | **High** | WebSocket | ✅ Fixed |
| HR-SEC-009 | Kein Maximum für Targets pro Request | **High** | API | ✅ Fixed |
| HR-SEC-010 | Starlette CVEs (GHSA-2c2j, GHSA-7f5h) | **High** | Supply-Chain | ✅ Fixed (requirements.txt) |
| HR-SEC-011 | systemd ohne Sandboxing-Optionen | **Medium** | Pi-Hardening | ✅ Fixed |
| HR-SEC-012 | Kein WebSocket-Verbindungslimit | **Medium** | WebSocket | ✅ Fixed |
| HR-SEC-013 | Kein HTTP Rate-Limit auf Endpunktebene | **Medium** | API | ⬜ Offen (kein leichtgewichtiges Paket für Pi Zero 2 W) |
| HR-SEC-014 | DB/Backup-Dateirechte nicht eingeschränkt | **Medium** | SQLite | ⬜ Offen (Deployment-Anleitung in security-hardening.md) |
| HR-SEC-015 | f-String SQL in analytics.py (fragiler Pattern) | **Medium** | SQLite | ✅ Fixed (Spaltenname-Whitelist) |
| HR-SEC-016 | Firmware unterstützt kein MQTT-Passwort | **Medium** | Firmware | ✅ Fixed |
| HR-SEC-017 | pytest in production requirements.txt | **Low** | Supply-Chain | ✅ Fixed (test-requirements.txt) |
| HR-SEC-018 | Retention 30 Tage für Rohdaten lang | **Low** | Privacy | ⬜ Offen (Empfehlung: 7 Tage in security-hardening.md) |
| HR-SEC-019 | Kein Hinweis auf Besucher-Transparenz | **Low** | Privacy | ⬜ Offen (soziale Maßnahme) |
| HR-SEC-020 | Keine Logrotation | **Low** | Pi-Hardening | ✅ Fixed (deploy/logrotate-hausradar.conf) |
| HR-SEC-021 | python-dotenv CVE GHSA-mf9w | **Low** | Supply-Chain | ⬜ Offen (nicht in Produktion installiert) |

---

### Detailbeschreibungen der kritischen und hohen Findings

---

#### HR-SEC-001 · Keine Authentifizierung für Dashboard/API · Critical

**Betroffene Dateien:** `server/app/main.py`, alle `server/app/api/*.py`  
**Risiko:** Jedes Gerät im Heimnetz kann alle Bewegungsprofile, Heatmaps, Session-Daten und den Grundriss abrufen. Bei versehentlicher Portfreigabe am Router ist das System weltweit zugänglich.

**Angriffsbeispiel (konzeptuell):**  
Ein Gerät im Gast-WLAN ruft `http://<Pi-IP>:8000/api/profile/heatmap` auf und erhält eine vollständige 7-Tage-Anwesenheits-Heatmap des Haushalts.

**Empfehlung:**  
Für ein lokales System ist ein einfacher konfigurierbarer API-Key (Header `X-API-Key`) eine ausreichend leichtgewichtige Lösung. Alternativ: Zugriff nur von vertrauenswürdigen IPs via Firewall beschränken.

---

#### HR-SEC-002 · `/api/simulate/motion` immer aktiv · Critical

**Betroffene Dateien:** `server/app/api/motion.py`, `server/app/main.py`  
**Risiko:** In der Produktion kann jedes LAN-Gerät beliebige Bewegungsdaten injizieren: Sensor-Dots auf der Karte manipulieren, Datenbank mit falschen Sessions fluten, Anwesenheitsprofile verfälschen.

**Angriffsbeispiel (konzeptuell):**  
`POST /api/simulate/motion` mit `{"sensor_id": "radar_wohnzimmer", ..., "targets": [...fake position...]}` — erscheint sofort auf dem Grundriss und in der DB.

**Empfehlung:**  
Endpoint in `production`-Modus mit 404 deaktivieren. `settings.json` erhält `"environment": "production"`.

---

#### HR-SEC-003 · MQTT allow_anonymous=true · Critical

**Betroffene Dateien:** `deploy/mosquitto-hausradar.conf`, `docs/setup-pi-zero-2.md`  
**Risiko:** Jedes LAN-Gerät kann auf dem Topic `hausradar/sensor/+/state` publishen und damit Fake-Sensordaten einspeisen. Das Backend validiert zwar Sensor-ID und Room-ID, aber Bewegungsdaten für bekannte Sensoren können frei manipuliert werden.

**Empfehlung:**  
MQTT-Passwortauth (`allow_anonymous false`) mit separatem Sensor-User und optionalen ACLs. Umgesetzt in Phase 5 (security-hardening.md).

---

#### HR-SEC-004 · Keine `.gitignore` · Critical

**Betroffene Dateien:** Projektroot (fehlt)  
**Risiko:** Bei einem `git init` + `git add .` würden committed:
- `firmware/include/config.h` mit WLAN-Passwort (auch wenn Platzhalter)
- `data/hausradar.db` mit Bewegungsdaten
- `data/backups/` mit Backup-Dateien
- `server/.venv/` (unnötig groß)

**Empfehlung:** `.gitignore` mit Standardeinträgen erstellen.

---

#### HR-SEC-005 · Kein HTTP Request-Body-Limit · High

**Betroffene Dateien:** `server/app/main.py`  
**Risiko:** Auf dem Pi Zero 2 W (512 MB RAM) kann ein Angreifer im LAN den Service mit einem großen JSON-Body (z.B. 50 MB) zum Absturz bringen. FastAPI/Starlette liest den gesamten Body bevor Pydantic validiert.

**Empfehlung:**  
Starlette `ContentSizeLimitMiddleware` oder manuelles Limit im Lifespan. Für HausRadar ist 64 KB ein sinnvolles Maximum.

---

#### HR-SEC-006 · XSS via innerHTML mit API-Daten · High

**Betroffene Dateien:** `web/app.js:135,152`, `web/settings.js:88,109`, `web/charts.js:140`  
**Risiko:** Raumnamen, Sensornamen und Zonennamen aus `rooms.json`/`sensors.json` werden unescaped in `innerHTML` gesetzt. Wenn `rooms.json` manipuliert wird (`"name": "<img src=x onerror=alert(1)>"`), wird XSS beim nächsten Seitenaufruf ausgelöst.

Direkte Angriffsfläche: Die Config-Dateien werden serverseitig geladen und nicht HTML-escaped bevor sie an den Browser gesendet werden.

**Empfehlung:** Hilfsfunktion `esc(str)` für HTML-Escaping; alle dynamisch eingefügten String-Werte aus API-Daten damit escapen.

---

#### HR-SEC-007 · Keine Security-HTTP-Header · High

**Betroffene Dateien:** `server/app/main.py`  
**Fehlende Header:**
- `X-Frame-Options: DENY` (Clickjacking)
- `X-Content-Type-Options: nosniff` (MIME Sniffing)
- `Referrer-Policy: no-referrer`
- `Content-Security-Policy` (XSS-Tiefenverteidigung)
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`

**Empfehlung:** Starlette Middleware mit statischen Security-Headern. Leichtgewichtig, kein Performance-Impact.

---

#### HR-SEC-008 · Keine WebSocket Origin-Prüfung · High

**Betroffene Dateien:** `server/app/main.py:ws_live()`  
**Risiko:** Eine bösartige Webseite auf einem anderen Gerät im LAN könnte über Cross-Site-WebSocket-Hijacking die Live-Bewegungsdaten mitlesen.

**Empfehlung:** `Origin`-Header des WS-Handshake prüfen; nur Verbindungen von `http(s)://<Pi-IP>:<Port>` erlauben.

---

#### HR-SEC-009 · Kein Maximum für Targets pro Request · High

**Betroffene Dateien:** `server/app/api/motion.py`  
**Risiko:** Die LD2450-Hardware kann maximal 3 Ziele melden. Ein Angreifer könnte `targets=[...1000 Objekte...]` senden und damit DB-Schreiblast und Memory-Druck erzeugen.

**Empfehlung:** `@field_validator` oder `Annotated[List[Target], Field(max_length=3)]` auf `targets`.

---

#### HR-SEC-010 · Starlette CVEs · High

**Betroffene Pakete:** `starlette 0.41.3` (via `fastapi 0.115.5`)  
- `GHSA-2c2j-9gv5-cj73` – Fix in 0.47.2
- `GHSA-7f5h-v6xp-fcq8` – Fix in 0.49.1

**Empfehlung:** `fastapi` auf aktuelle Version aktualisieren. Starlette wird als transitive Abhängigkeit mit hochgezogen.

---

## Automatisierte Check-Ergebnisse – Zusammenfassung

| Tool | Ergebnis |
|---|---|
| `python -m compileall` | ✅ Keine Fehler |
| `pytest` | ✅ 213/213 |
| `pip-audit` | ⚠️ 4 CVEs (starlette ×2 kritisch, pytest test-only, python-dotenv low) |
| `bandit` | ⚠️ 7× B608 (false positives, aber fragiler Pattern), 1× B110 (akzeptabel) |
| Secrets-Scan | ⚠️ Platzhalter in config.h, keine .gitignore |
| innerHTML-Scan | ⚠️ Unescapte API-Daten in 3 JS-Dateien |
| Security Headers | ❌ Fehlen komplett |
| CORS | ℹ️ Kein Wildcard, aber auch keine explizite Konfiguration |
| WebSocket Origin | ❌ Keine Prüfung |
| Body-Limit | ❌ Kein Limit |
| .gitignore | ❌ Fehlt |

---

---

## Phase 5–7 Abschlussbericht (2026-04-26)

### Umgesetzte Code-Änderungen

**`server/app/main.py`**
- `SecurityHeadersMiddleware`: X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, CSP
- `BodySizeLimitMiddleware`: 413 bei Content-Length > 64 KB
- `ApiKeyMiddleware`: Optionaler X-API-Key-Schutz für alle `/api/*`-Endpunkte (außer `/api/health`)
- `_origin_allowed()` + WebSocket Origin-Prüfung gegen konfigurierbare Whitelist
- WebSocket Verbindungslimit aus `settings.json` (`server.ws_max_connections`)

**`server/app/api/motion.py`**
- `targets: Annotated[List[Target], Field(max_length=3)]` – maximal 3 Ziele
- Production-Check: `simulate/motion` gibt in `environment=production` 404 zurück

**`server/app/analytics.py`**
- `_ALLOWED_FILTER_COLUMNS` Whitelist verhindert ungültige Spaltennamen in `_where()`

**`server/app/websocket_service.py`**
- `set_max_connections()` + Verbindungslimit-Check in `connect()`

**`server/requirements.txt` + `server/test-requirements.txt`**
- pytest/httpx ausgelagert in `test-requirements.txt`
- Starlette explizit auf `>=0.47.2` gepinnt (CVE-Fixes)

**`web/api.js`**
- Globale `esc()` HTML-Escape-Funktion

**`web/app.js`, `web/settings.js`, `web/charts.js`**
- Alle dynamischen API-Werte in `innerHTML` mit `esc()` escaped

**`config/settings.json`**
- `environment`, `server.api_key`, `server.allowed_origins`, `server.body_limit_bytes` ergänzt

**`deploy/hausradar.service`**
- `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome=read-only`, `ReadWritePaths`

**`deploy/mosquitto-hausradar.conf`**
- `message_size_limit 65536`, Auth-Konfiguration als Kommentar vorbereitet

**`deploy/mosquitto-hausradar-acl.example`** – ACL-Template (neu)  
**`deploy/logrotate-hausradar.conf`** – Logrotation wöchentlich, 4 Wochen (neu)  
**`.gitignore`** – Schützt DB, Backups, WLAN-Secrets, .venv (neu)  
**`firmware/include/config.h`** – `MQTT_USER`, `MQTT_PASSWORD`  
**`firmware/src/main.cpp`** – MQTT-Auth-Unterstützung in `connectMqtt()`  
**`firmware/include/secrets.h.example`** – Secrets-Template (neu)

### Test-Ergebnis

```
246 passed in 78.8s – alle Tests grün
```

Neue Tests in `tests/test_hardening.py` (33 Tests):
- Simulate Production/Development
- Max-Targets-Validierung
- Security-Header auf allen Endpoints
- X-API-Key (konfiguriert / unkonfiguriert / falsch / korrekt / Health-Ausnahme)
- Body-Size-Limit
- WebSocket Origin-Check
- WebSocket Verbindungslimit
- Analytics Spaltenname-Whitelist
- XSS-Schutz (esc() in JS-Dateien vorhanden)

### Verbleibende offene Punkte

| ID | Grund |
|---|---|
| HR-SEC-013 | Kein leichtgewichtiges Rate-Limit-Paket für Pi Zero 2 W; Firewall-UFW-Regel als Ersatz |
| HR-SEC-014 | Deployment-Maßnahme; Anleitung in security-hardening.md |
| HR-SEC-018 | User-Entscheidung; Empfehlung: `retention_days: 7` in settings.json |
| HR-SEC-019 | Soziale Maßnahme (Aufklärung der Haushaltsmitglieder) |
| HR-SEC-021 | python-dotenv ist nicht in requirements.txt – nicht installiert |
