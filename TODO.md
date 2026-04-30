# HausRadar – Aufgabenliste

## Version 1.0 – Alle Milestones abgeschlossen ✅

| Milestone | Thema | Status |
|---|---|---|
| 1 | Minimalversion Backend + Frontend | ✅ |
| 2 | Konfiguration und Validierung | ✅ |
| 3 | Koordinatensystem | ✅ |
| 4 | Simulation ohne Hardware | ✅ |
| 5 | WebSocket Live-Daten | ✅ |
| 6 | SVG-Grundriss | ✅ |
| 7 | Bewegungsspuren | ✅ |
| 8 | SQLite-Datenbank | ✅ |
| 9 | Bewegungsprofile | ✅ |
| 10 | Diagramme im Frontend | ✅ |
| 11 | MQTT einbauen | ✅ |
| 12 | ESP32-Firmware (Simulation) | ✅ |
| 13 | ESP32-Firmware (echter LD2450-Parser) | ✅ |
| 14 | Raspberry-Pi-Installation | ✅ |
| 15 | Robustheit | ✅ |
| 16 | Oberfläche polieren | ✅ |
| — | Security Audit + Hardening | ✅ |
| — | Kalibrierungs-Übersicht und Inline-Editing | ✅ |
| — | Raum- und Sensor-Verwaltung | ✅ |
| — | BFS Auto-Layout | ✅ |
| — | Web-Update-Manager mit Rollback | ✅ |
| — | Versionsmanagement (VERSION-Datei, Badges) | ✅ |
| — | Personen-Tracking (Nearest-Neighbour, Ghost-Frames) | ✅ |
| — | Farbkodierung pro Person | ✅ |
| — | Sensor-Identifikation via WebSocket | ✅ |

---

## Post-1.0 – Ideen und offene Punkte

### Funktional
- [ ] Mehrere Sensoren pro Raum (Tracking über Sensorgrenze hinweg)
- [ ] Personen-Zähler in Echtzeit je Raum (inkl. Anzeige im Grundriss)
- [ ] Benachrichtigungen (Push / Webhook) bei Bewegung in definierten Zonen
- [ ] Abwesenheitserkennung: Alarm wenn lange keine Bewegung im ganzen Haus
- [ ] Schlafzonen-Tracking: ruhige vs. aktive Bewegungsmuster unterscheiden
- [ ] Datenexport (CSV / JSON) über die Weboberfläche

### Technisch
- [ ] MQTT-Authentifizierung (User/Passwort) vollständig per Weboberfläche konfigurierbar
- [ ] Automatisches Datenbank-Backup per Weboberfläche anstoßen
- [ ] Logs im Browser einsehbar (letzte N Zeilen von journalctl)
- [ ] Sensor-Kalibrierung direkt mit ESP32-Simulation testbar
- [ ] Unit-Tests für `tracker.py` und neue API-Endpunkte (rooms CRUD, sensors CRUD, update)
- [ ] Screenshots in README ergänzen
