# HausRadar – Setup Raspberry Pi Zero 2 W

## Voraussetzungen

- Raspberry Pi Zero 2 W mit Raspberry Pi OS Lite (Bookworm, 64-Bit empfohlen)
- MicroSD-Karte ≥ 8 GB (A1-Rating empfohlen)
- WLAN-Verbindung konfiguriert
- SSH-Zugang aktiv

---

## 1. Raspberry Pi OS vorbereiten

Mit dem **Raspberry Pi Imager** (empfohlen):

1. OS: **Raspberry Pi OS Lite (64-Bit)** wählen
2. Zahnrad-Icon → Erweiterte Optionen:
   - Hostname: `hausradar`
   - SSH aktivieren
   - WLAN-Zugangsdaten eintragen
3. Image auf SD-Karte schreiben, einlegen, starten

Per SSH verbinden:
```bash
ssh pi@hausradar.local
```

---

## 2. Repository auf den Pi klonen

```bash
sudo apt-get install -y git
git clone https://github.com/monstertobs/hausradar.git ~/hausradar
```

---

## 3. Installations-Skript ausführen

```bash
cd ~/hausradar
bash scripts/install_pi.sh
```

Das Skript erledigt automatisch:
- System-Pakete installieren (`python3-venv`, `mosquitto`, `sqlite3`, `git`)
- Python-Virtualenv erstellen und Abhängigkeiten installieren
- Datenbankverzeichnis und Log-Verzeichnis anlegen
- Mosquitto für das LAN konfigurieren (Port 1883, anonym erlaubt)
- systemd-Service `hausradar` aus dem Template `deploy/hausradar.service` einrichten
- sudoers-Eintrag setzen (für Web-Update ohne Passwort nötig)
- Service starten und aktivieren

Nach erfolgreicher Installation erscheint:
```
╔══════════════════════════════════════════════╗
║  HausRadar erfolgreich installiert!          ║
╚══════════════════════════════════════════════╝

  Weboberfläche:   http://192.168.1.xxx:8000
  MQTT-Broker:     192.168.1.xxx:1883
```

---

## 4. Erste Schritte nach der Installation

### Service-Status prüfen
```bash
systemctl status hausradar
journalctl -u hausradar -f          # Live-Log
```

### Weboberfläche öffnen
```
http://hausradar.local:8000
```

### Simulation starten (ohne echte Sensoren)
```bash
cd ~/hausradar
source server/.venv/bin/activate
python3 scripts/simulate_sensor_data.py --mqtt --interval 0.3
```

---

## 5. ESP32-Sensoren einrichten

### Sensor identifizieren (welcher ESP32 ist welcher?)

In der Weboberfläche unter **Einstellungen → Sensoren** siehst du pro Sensor:
- Live-Status (online / offline)
- Das **MQTT-Topic** `hausradar/sensor/{id}/state` – das ist die `sensor_id`
- Einen **„📡 Identifizieren"**-Button: Klicken, dann vor den Sensor bewegen → Karte bestätigt welcher es ist

### Firmware konfigurieren

```bash
# Zugangsdaten anlegen (einmalig)
cp firmware/esp32-ld2450-mqtt/include/secrets.h.example \
   firmware/esp32-ld2450-mqtt/include/secrets.h

# secrets.h bearbeiten: WLAN-SSID und -Passwort eintragen
nano firmware/esp32-ld2450-mqtt/include/secrets.h

# config.h anpassen: Pi-IP und Sensor-ID eintragen
nano firmware/esp32-ld2450-mqtt/include/config.h
# MQTT_HOST  → IP-Adresse des Raspberry Pi (z.B. 192.168.178.100)
# SENSOR_ID  → ID aus sensors.json (z.B. "radar_wohnzimmer")
# ROOM_ID    → Raum-ID aus rooms.json
```

```bash
# Flashen
cd firmware/esp32-ld2450-mqtt
pio run -e esp32dev -t upload         # echter Sensor
pio run -e esp32dev-sim -t upload     # Simulation

# Serielle Ausgabe überwachen
pio device monitor
```

---

## 6. Software-Updates einspielen

### Empfohlen: Web-Update im Browser

Im Browser unter **Einstellungen → SOFTWARE-UPDATE**:
1. „🔍 Auf Updates prüfen" klicken
2. Neue Version wird angezeigt
3. „Update installieren" klicken
4. Fortschrittsbalken und Log verfolgen
5. Seite lädt nach Service-Neustart automatisch neu

Das Update sichert die Konfiguration, aktualisiert Code und Pakete und stellt bei
Fehlern automatisch den alten Stand wieder her.

### Alternativ: Skript auf dem Pi

```bash
cd ~/hausradar && bash scripts/update_pi.sh
```

---

## 7. Automatisches Datenbank-Backup

Tägliches Backup per Cron einrichten:
```bash
crontab -e
# Folgende Zeile einfügen:
0 3 * * * /home/pi/hausradar/scripts/backup_db.sh >> /var/log/hausradar/backup.log 2>&1
```

Manuelles Backup:
```bash
bash ~/hausradar/scripts/backup_db.sh
# Backups: ~/hausradar/data/backups/
```

---

## 8. Service-Management

| Aktion | Befehl |
|--------|--------|
| Status | `systemctl status hausradar` |
| Starten | `sudo systemctl start hausradar` |
| Stoppen | `sudo systemctl stop hausradar` |
| Neustart | `sudo systemctl restart hausradar` |
| Log | `journalctl -u hausradar -n 50` |
| Live-Log | `journalctl -u hausradar -f` |

---

## 9. Ressourcen-Hinweise (Pi Zero 2 W)

| Ressource | Empfehlung |
|-----------|------------|
| RAM | 512 MB gesamt; HausRadar ≤ 256 MB (MemoryMax im Service) |
| CPU | Single-Worker uvicorn reicht für 5+ Sensoren |
| SD-Karte | A1-Rating empfohlen (bessere zufällige I/O-Performance) |
| Kühlung | Optionaler kleiner Kühlkörper bei Dauerbetrieb |
| Netzteil | Mind. 2,5 A für stabilen Betrieb |

Der systemd-Service limitiert den Speicher auf 256 MB. Bei Überschreitung
wird der Prozess neu gestartet (kein Datenverlust durch SQLite WAL-Mode).

---

## 10. Fehlerbehebung

Ausführliche Anleitung: **[docs/troubleshooting.md](troubleshooting.md)**

**Backend nicht erreichbar:**
```bash
curl http://localhost:8000/api/health
journalctl -u hausradar -n 30
```

**MQTT-Verbindung schlägt fehl:**
```bash
systemctl status mosquitto
mosquitto_sub -h localhost -t "hausradar/#" -v   # Nachrichten mithören
```

**Sensor erscheint offline obwohl er sendet:**
```bash
curl http://localhost:8000/api/live | python3 -m json.tool
# last_seen_seconds_ago prüfen
```

**Datenbank beschädigt (selten):**
```bash
sqlite3 ~/hausradar/data/hausradar.db "PRAGMA integrity_check;"
# Bei Fehler: Backup einspielen
cp ~/hausradar/data/backups/hausradar_DATUM.db ~/hausradar/data/hausradar.db
sudo systemctl restart hausradar
```
