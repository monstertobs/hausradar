# HausRadar – Setup Raspberry Pi Zero 2 W

## Voraussetzungen

- Raspberry Pi Zero 2 W mit Raspberry Pi OS Lite (Bullseye oder Bookworm, 64-Bit)
- MicroSD-Karte ≥ 8 GB
- WLAN-Verbindung konfiguriert (z.B. via `raspi-config` oder `imager`)
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

## 2. Repository auf den Pi kopieren

**Option A – per scp vom Entwicklungs-Mac:**
```bash
scp -r /Users/tobs/Claude/Hausradar/hausradar pi@hausradar.local:~/hausradar
```

**Option B – git clone (falls git installiert):**
```bash
sudo apt-get install -y git
git clone <repo-url> ~/hausradar
```

---

## 3. Installations-Skript ausführen

```bash
cd ~/hausradar
bash scripts/install_pi.sh
```

Das Skript erledigt automatisch:
- System-Pakete installieren (`python3-venv`, `mosquitto`, `sqlite3`)
- Python-Virtualenv erstellen und Abhängigkeiten installieren
- Mosquitto für das LAN konfigurieren
- systemd-Service `hausradar` einrichten und starten

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

### Simulation starten (ohne echte Sensoren)
```bash
cd ~/hausradar
source server/.venv/bin/activate
python3 scripts/simulate_sensor_data.py --mqtt
```

### Service-Status prüfen
```bash
systemctl status hausradar
journalctl -u hausradar -f          # Live-Log
```

### Weboberfläche öffnen
```
http://hausradar.local:8000
```

---

## 5. ESP32-Sensoren verbinden

In der Firmware-Konfiguration (`firmware/esp32-ld2450-mqtt/include/config.h`):
```c
#define MQTT_HOST   "192.168.1.xxx"   // Pi-IP eintragen
```

Flashen:
```bash
cd firmware/esp32-ld2450-mqtt
pio run -e esp32dev -t upload         # echter Sensor
pio run -e esp32dev-sim -t upload     # Simulation
```

---

## 6. Automatisches Datenbank-Backup

Tägliches Backup per Cron einrichten:
```bash
crontab -e
```
Folgende Zeile einfügen:
```
0 3 * * * /home/pi/hausradar/scripts/backup_db.sh >> /var/log/hausradar/backup.log 2>&1
```

Manuelles Backup:
```bash
bash ~/hausradar/scripts/backup_db.sh
# Backups liegen in: ~/hausradar/data/backups/
```

---

## 7. Service-Management

| Aktion | Befehl |
|--------|--------|
| Status | `systemctl status hausradar` |
| Starten | `sudo systemctl start hausradar` |
| Stoppen | `sudo systemctl stop hausradar` |
| Neustart | `sudo systemctl restart hausradar` |
| Log | `journalctl -u hausradar -n 50` |
| Live-Log | `journalctl -u hausradar -f` |

---

## 8. Ressourcen-Hinweise (Pi Zero 2 W)

| Ressource | Empfehlung |
|-----------|------------|
| RAM | 512 MB gesamt; HausRadar ≤ 256 MB (MemoryMax im Service) |
| CPU | Single-Worker uvicorn reicht für 5 Sensoren |
| SD-Karte | A1-Rating empfohlen (bessere zufällige I/O-Performance) |
| Kühlung | Optionaler kleiner Kühlkörper bei Dauerbetrieb |

Der systemd-Service limitiert den Speicher auf 256 MB. Bei Überschreitung
wird der Prozess neu gestartet (kein Datenverlust durch SQLite).

---

## 9. Fehlerbehebung

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

**Datenbank beschädigt (selten):**
```bash
sqlite3 ~/hausradar/data/hausradar.db "PRAGMA integrity_check;"
# Bei Fehler: Backup einspielen
cp ~/hausradar/data/backups/hausradar_DATUM.db ~/hausradar/data/hausradar.db
sudo systemctl restart hausradar
```
