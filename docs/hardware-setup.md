# HausRadar – Hardware-Aufbau und Kalibrierung

**Zielgruppe:** Bastler ohne tiefe Elektronikkenntnisse  
**Schwierigkeit:** Mittel (kein Löten nötig, aber Sorgfalt erforderlich)  
**Zeitbedarf pro Raum:** ca. 1–2 Stunden für Erstaufbau + Kalibrierung

---

## 1. Überblick

HausRadar erkennt Bewegungen in Räumen mithilfe von mmWave-Radarsensoren – **ohne Kamera, ohne Bild, ohne Cloud**.

### Was das System macht

- Jeder Raum bekommt einen Radarsensor (HLK-LD2450), der Personen als Koordinatenpunkte meldet
- Ein kleiner Computer (Raspberry Pi Zero 2 W) sammelt alle Daten und zeigt sie in einer Webseite an
- Du kannst von jedem Gerät im Heimnetz den Grundriss mit Live-Bewegungspunkten sehen

### Systemaufbau auf einen Blick

```
┌─────────────┐      UART       ┌──────────────┐     WLAN / MQTT     ┌─────────────────────┐
│ HLK-LD2450  │ ──────────────► │    ESP32     │ ──────────────────► │ Raspberry Pi Zero   │
│ (Radar)     │  256000 Baud    │ (Mikro-      │  hausradar/sensor/  │ 2 W                 │
│             │  GPIO16 = RX2   │  controller) │  radar_X/state      │ ┌─────────────────┐ │
└─────────────┘                 └──────────────┘                      │ │ Mosquitto MQTT  │ │
                                                                       │ │ FastAPI Backend │ │
pro Raum je 1×                 pro Raum je 1×                         │ │ SQLite DB       │ │
                                                                       │ │ Weboberfläche   │ │
                                                                       │ └─────────────────┘ │
                                                                       └─────────────────────┘
                                                                                │
                                                                                ▼
                                                                       Browser (jedes Gerät
                                                                       im Heimnetz)
```

### Warum ein ESP32 pro Raum?

- Der ESP32 ist günstig (ca. 5–10 €), kompakt und hat eingebautes WLAN
- Er wandelt die LD2450-Rohdaten in JSON um und sendet sie per MQTT ans Netz
- Der Raspberry Pi würde zu schwer werden, wenn er in jedem Raum sitzen müsste
- Der Pi läuft genau einmal: als zentraler Server für alle Sensoren gleichzeitig

### Warum kein eigener Pi pro Sensor?

- Ein Pi Zero 2 W kostet ca. 15–20 €, braucht ein eigenes Netzteil, Karte und Konfiguration
- Ein ESP32 ist kleiner, sparsamer und kostet ein Drittel
- Die gesamte Rechenarbeit (Koordinatenumrechnung, Speicherung, Webseite) läuft einmal auf dem Pi

---

## 2. Einkaufsliste

### Pro Sensorstation (1× pro Raum)

| Menge | Komponente | Hinweise |
|---|---|---|
| 1× | **HLK-LD2450** mmWave-Radar | 24-GHz-Sensor; achte auf originale HiLink-Ware |
| 1× | **ESP32 Dev Board** | z.B. AZ-Delivery ESP32 DevKitC v4, oder LOLIN D32 |
| 1× | USB-C-Kabel (zum Flashen und Betrieb) | kurz, gute Qualität; schlechte Kabel = häufigste Fehlerquelle |
| 1× | USB-Netzteil 5 V / mind. 1 A | handelsüblich; 2 A empfohlen |
| 4× | Dupont-Kabel, Buchse–Buchse | zum Verbinden der Pins |
| optional | Gehäuse (Kunststoff) | z.B. 3D-gedruckt oder kleine Plastikdose |
| optional | JST-Stecker oder Schraubklemmen | für ordentlichere Verbindungen |
| optional | Klebeband/Klebepads | zur provisorischen Montage während Kalibrierung |

### Zentrale (1× im ganzen Haus)

| Menge | Komponente | Hinweise |
|---|---|---|
| 1× | **Raspberry Pi Zero 2 W** | Mit WLAN onboard |
| 1× | MicroSD-Karte, ≥ 8 GB | A1-Rating empfohlen (z.B. SanDisk Endurance) |
| 1× | Netzteil 5 V / 2,5 A, Micro-USB | offizielles Pi-Netzteil bevorzugt |
| 1× | Micro-USB-Kabel | für den Pi |
| 1× | Laptop / Mac / PC | zum Flashen, SSH, Konfigurieren |

### Optional für festen Einbau

| Komponente | Wozu |
|---|---|
| 12-V-Netzteil (Hutschiene/Industrie) | zentrale Stromversorgung aller Sensoren |
| Step-Down-Wandler 12V→5V (Buck Converter) | pro Sensor einer, z.B. LM2596-Modul |
| WAGO-Klemmen | ordentliche Stromverteilung |
| Sicherungshalter + 1-A-Sicherungen | Schutz je Sensor-Abzweig |
| Kabelbinder, Kabelkanal | Verlegung |
| Maßband oder iPhone-Lineal-App | zum Raum vermessen |
| Multimeter | Spannung prüfen – **sehr empfohlen** |

---

## 3. Benötigte Werkzeuge

| Werkzeug | Benötigt | Wofür |
|---|---|---|
| Laptop / Mac / PC | **Pflicht** | Firmware flashen, SSH zum Pi |
| USB-C-Kabel, gute Qualität | **Pflicht** | Flashen + Betrieb ESP32 |
| Maßband | **Pflicht** | Raum vermessen |
| Kleines Kreuzschraubendreher-Set | Empfohlen | Gehäuse, Montage |
| Multimeter | **Sehr empfohlen** | Spannungen messen, Fehlersuche |
| Seitenschneider / Abisolierer | Optional | Kabel kürzen |
| Lötkolben | Optional | nur für Schraubklemmen/Stecker |
| Klebepads / doppelseitiges Klebeband | Empfohlen | provisorische Montage |
| Handy mit Kamera / Notizblock | Empfohlen | Sensorposition dokumentieren |

---

## 4. Sicherheitshinweise

> ⚠️ **Bitte vor dem Aufbau lesen – auch wenn du erfahren bist.**

### Strom und Spannung

- Arbeite **niemals direkt an 230-V-Leitungen** – das ist nichts für dieses Projekt
- Verwende nur **geprüfte Netzteile** mit CE-Kennzeichnung
- Alle Komponenten arbeiten mit **5 V DC** (Gleichstrom) – das ist ungefährlich
- Trotzdem: **Kurzschlüsse vermeiden** – ein Kurzschluss kann ESP32 oder LD2450 dauerhaft zerstören
- **Polung prüfen**: GND ist GND, VCC ist VCC – vertauschte Polung kann Bauteile zerstören

### Mechanik und Aufbau

- Lege ESP32 und LD2450 **nicht lose in Metallgehäuse** – Kurzschlussgefahr
- Verwende **Kunststoffgehäuse** oder stelle sicher, dass Platinen auf Abstandshaltern sitzen
- **Keine offenen Kontakte** im Dauerbetrieb – alles ordentlich in ein Gehäuse
- Kabel unter Zugentlastung verlegen – ein losgerissener Stecker beim Heizputzen ist ärgerlich

### Vor der Montage

- Teste **immer zuerst auf dem Schreibtisch**, bevor du etwas fest montierst
- **Spannungen messen** bevor du anschließt: Step-Down-Wandler vor dem Anschließen auf 5 V einstellen
- Bei zentraler 12-V-Versorgung: Sicherungen (1 A pro Sensor) verwenden

### ESP32 und LD2450 spezifisch

- **Nicht mit falscher Spannung betreiben** – prüfe deinen LD2450-Typ (→ Abschnitt 5)
- Der ESP32 wird **über USB-C versorgt** und ist damit sicher
- Beim Flashen: WLAN-Credentials sind im Klartext in `config.h` – diese Datei **nicht in öffentliche Git-Repos** pushen (ist durch `.gitignore` geschützt)

---

## 5. Pinbelegung HLK-LD2450

> ⚠️ **Annahme – prüfe am eigenen Modul!**
> Die Beschriftung auf Breakout-Boards kann je nach Hersteller und Version abweichen.
> Schau immer auf den Aufdruck **auf deinem Modul** oder im mitgelieferten Datenblatt.

### Typische Pinbelegung (4-Pin-Anschluss)

| Pin | Bezeichnung | Beschreibung |
|---|---|---|
| 1 | **VCC** | Versorgungsspannung |
| 2 | **GND** | Masse (Minus) |
| 3 | **TX** | Daten vom Sensor zum ESP32 (Sensor sendet) |
| 4 | **RX** | Daten vom ESP32 zum Sensor (für Konfiguration, optional) |

### Versorgungsspannung

> ⚠️ **Annahme – prüfe Datenblatt / Modulaufdruck!**
>
> - Einige LD2450-Module laufen mit **3,3 V** (direkt am ESP32-3V3-Pin)
> - Andere laufen mit **5 V** (vom ESP32-5V/VIN-Pin oder USB)
> - Die **UART-Datenleitungen** (TX/RX) arbeiten immer mit **3,3-V-Pegel** und sind direkt ESP32-kompatibel
> - Falsches Betreiben kann das Modul zerstören – im Zweifel Datenblatt herunterladen

Die folgende Tabelle zeigt beide häufigen Varianten:

| Modulvariante | VCC |
|---|---|
| LD2450 Bare-Modul (ohne Breakout) | Prüfe Datenblatt |
| LD2450 auf Breakout-Board mit 3,3-V-Regler | VCC → 3,3 V (ESP32-Pin 3V3) |
| LD2450 auf Breakout-Board ohne Regler | VCC → 5 V (ESP32-Pin VIN oder 5V) |

### TX und RX: gekreuzt anschließen

Ein häufiger Fehler: TX und RX müssen **gekreuzt** werden:

```
Sensor TX  ──►  ESP32 RX  (Sensor sendet, ESP32 empfängt)
Sensor RX  ──►  ESP32 TX  (ESP32 sendet, Sensor empfängt)
```

Der Sensor **sendet** Daten auf seinem TX-Pin. Diese Daten muss der ESP32 auf seinem **RX-Pin** empfangen. Deshalb: TX→RX.

---

## 6. Anschluss HLK-LD2450 an ESP32

### Anschlusstabelle

| HLK-LD2450 | ESP32 | Hinweis |
|---|---|---|
| VCC | 3V3 oder VIN/5V | Prüfe Modulvariante (Abschnitt 5) |
| GND | GND | Muss immer verbunden sein |
| TX | **GPIO16** (UART2-RX) | Sensor sendet → ESP32 empfängt |
| RX | **GPIO17** (UART2-TX) | ESP32 sendet → Sensor empfängt |

> **GPIO16 und GPIO17** sind die Standardwerte in `firmware/esp32-ld2450-mqtt/include/config.h`. Du kannst sie ändern, wenn an diesen Pins etwas anderes hängt – passe dann `LD2450_RX_PIN` und `LD2450_TX_PIN` an.

### ASCII-Schaltbild

```
HLK-LD2450           ESP32 Dev Board
┌──────────┐         ┌──────────────┐
│          │         │              │
│   VCC ───┼─────────┼─ 3V3 (oder  │
│          │         │   VIN/5V)    │
│   GND ───┼─────────┼─ GND         │
│          │         │              │
│   TX  ───┼─────────┼─ GPIO16 (RX2)│  ← Sensor sendet Koordinaten
│          │         │              │
│   RX  ───┼─────────┼─ GPIO17 (TX2)│  ← ESP32 sendet (nur für Konfig)
│          │         │              │
└──────────┘         └──────────────┘

Baudrate: 256.000 Baud (fest im Sensor, nicht änderbar)
UART:     Hardware-Serial UART2 des ESP32
```

### Wichtige Hinweise zur Verkabelung

- **GND zuerst** verbinden, dann VCC, dann die Datenleitungen
- Dupont-Kabel fest einrasten lassen – wackelnde Kabel sind die häufigste Fehlerquelle
- Falls der Sensor stumm bleibt: TX/RX tauschen (oft vertauscht)
- **RX des Sensors (GPIO17)** ist technisch optional – der Sensor sendet auch ohne ihn

---

## 7. Stromversorgung

### Variante A: Einfacher Testaufbau mit USB-Netzteil (empfohlen für Anfänger)

```
USB-Netzteil (5V/1A oder 5V/2A)
        │
        │ USB-C-Kabel
        ▼
   ESP32 Dev Board
        │
        │ über Dupont-Kabel (3,3V oder 5V Pin)
        ▼
   HLK-LD2450
```

**Vorteile:**
- Einfachste Variante, wenig Fehlerquellen
- Ideal zum Testen und Kalibrieren
- Kein Multimeter nötig

**Nachteile:**
- Pro Sensor eine eigene Steckdose nötig
- Nicht ideal für fest eingebaute Sensoren an der Decke

**Empfehlung:** Mit dieser Variante starten!

---

### Variante B: Mehrfach-USB-Netzteil

Ein USB-Netzteil mit mehreren Ports versorgt mehrere Sensoren gleichzeitig.

```
USB-Mehrfachnetzteil (z.B. 30W, 6 Ports)
├── Port 1 → ESP32 Sensor Wohnzimmer
├── Port 2 → ESP32 Sensor Flur
├── Port 3 → ESP32 Sensor Küche
└── ...
```

**Hinweise:**
- Pro Sensor mindestens **500 mA** Reserve einplanen; 1 A pro Port empfohlen
- **Kurze USB-Kabel** verwenden – bei langen Kabeln fällt Spannung ab
- USB-Kabel mit dickem Kupferleiter (AWG 24 oder besser) bevorzugen
- Nicht mehr Ports nutzen als das Netzteil hergibt

---

### Variante C: Zentrale 12-V-Versorgung mit Step-Down-Wandlern

Sinnvoll wenn: fester Einbau im Haus, Kabel sollen ordentlich in Kabelkanal verlegt werden.

```
12-V-Netzteil (z.B. 2A Hutschienen-Netzteil)
        │
        ├── Kabel → Step-Down-Modul Sensor 1 → 5V → ESP32 + LD2450
        ├── Kabel → Step-Down-Modul Sensor 2 → 5V → ESP32 + LD2450
        └── Kabel → Step-Down-Modul Sensor 3 → ...
```

**Step-Down einstellen:**
1. Step-Down-Modul **ohne Last** ans 12-V-Netzteil anschließen
2. Multimeter an Ausgang halten
3. Potentiometer drehen bis **genau 5,0 V** angezeigt werden
4. Erst dann ESP32 und Sensor anschließen

**Vorteile:**
- Ideal für fest verlegte Kabel
- Saubere Installation, zentrale Sicherungen möglich
- Spannungsstabilität auch bei längeren Kabeln

**Nachteile:**
- Mehr Aufwand beim Aufbau
- Step-Down-Wandler müssen eingestellt werden

> **Empfehlung:** Für den Einstieg Variante A verwenden. Erst nach erfolgreichem Test und Kalibrierung zu Variante C wechseln wenn nötig.

---

## 8. Erstinbetriebnahme einer Sensorstation

Folge dieser Reihenfolge genau – sie spart Fehlersuche.

### Vorbereitung

Stelle sicher, dass:
- [ ] PlatformIO in VS Code installiert ist (→ [platformio.org](https://platformio.org))
- [ ] `firmware/esp32-ld2450-mqtt/include/config.h` angepasst wurde (WLAN, MQTT, Sensor-ID)
- [ ] Der Raspberry Pi läuft und HausRadar darauf installiert ist (→ `docs/setup-pi-zero-2.md`)

---

### Schritt 1: ESP32 alleine testen (ohne Sensor)

1. **ESP32 per USB-C an den Computer** anschließen (LD2450 noch nicht angeschlossen)
2. **Simulation-Firmware flashen** – so kannst du alles testen ohne echten Sensor:
   ```bash
   cd firmware/esp32-ld2450-mqtt
   pio run -e esp32dev-sim -t upload
   ```
3. **Seriellen Monitor öffnen** (115200 Baud):
   ```bash
   pio device monitor
   ```
4. Erwartete Ausgabe:
   ```
   HausRadar Fake-Sensor (Walker-Simulation)
     Sensor: radar_wohnzimmer  Raum: wohnzimmer  (6000 x 4500 mm)
   [WiFi] Verbinde mit "Mein-WLAN-Name" …........
   [WiFi] Verbunden  IP: 192.168.178.42
   [NTP]  Synchronisiere mit pool.ntp.org …
   [MQTT] Verbinde mit 192.168.178.99:1883 …
   [MQTT] Verbunden.
   [SIM] Raum ( 3412, 2789) mm → Sensor (  412, 2789) mm  v=143 mm/s
   [SIM] Raum ( 3489, 2801) mm → Sensor (  489, 2801) mm  v=143 mm/s
   ...
   ```

**Was tun wenn:**
- Kein Text erscheint → falsches COM-Port oder falscher Monitor-Speed (muss 115200 sein)
- `[WiFi] Verbindung fehlgeschlagen` → WLAN-Credentials in `config.h` prüfen; 2,4-GHz-Netz?
- `[MQTT] Fehlgeschlagen` → Pi-IP in `config.h` korrekt? Mosquitto auf Pi läuft?

---

### Schritt 2: MQTT-Daten auf dem Pi prüfen

Auf dem Raspberry Pi eingeben:
```bash
mosquitto_sub -h localhost -t 'hausradar/sensor/+/state' -v
```

Wenn die Simulation läuft, sollten Daten erscheinen:
```json
hausradar/sensor/radar_wohnzimmer/state {
  "sensor_id": "radar_wohnzimmer",
  "room_id": "wohnzimmer",
  "timestamp_ms": 1710000000000,
  "target_count": 1,
  "targets": [{"id": 1, "x_mm": 412, "y_mm": 2789, ...}]
}
```

---

### Schritt 3: Webseite prüfen

Im Browser auf einem Gerät im Heimnetz:
```
http://hausradar.local:8000
```

Der Grundriss sollte erscheinen und ein wandernder Punkt im Wohnzimmer sichtbar sein (Simulation).

---

### Schritt 4: Echte LD2450-Firmware flashen und Sensor anschließen

1. ESP32 **vom Computer trennen**
2. LD2450 gemäß Abschnitt 6 anschließen
3. **Echte Firmware flashen:**
   ```bash
   pio run -e esp32dev -t upload
   ```
4. **Strom anschließen** (ESP32 per USB-Netzteil)
5. **Seriellen Monitor öffnen:**
   ```bash
   pio device monitor
   ```
6. Erwartete Ausgabe:
   ```
   HausRadar LD2450-Sensor
     Sensor: radar_wohnzimmer  Raum: wohnzimmer  UART2 RX=GPIO16  256000 Baud
   [WiFi] Verbunden  IP: 192.168.178.42
   [MQTT] Verbunden.
   [LD2450] 0 Ziel(e)
   [LD2450] 0 Ziel(e)
   ```
7. **Vor den Sensor bewegen:**
   ```
   [LD2450] 1 Ziel(e)
   [LD2450] 1 Ziel(e)
   [LD2450] 0 Ziel(e)
   ```

---

### Erstinbetriebnahme Checkliste

- [ ] ESP32 startet (Text im seriellen Monitor erscheint)
- [ ] WLAN verbunden (IP-Adresse erscheint im Log)
- [ ] MQTT verbunden (`[MQTT] Verbunden.` im Log)
- [ ] Simulation zeigt Daten auf Webseite (Variante esp32dev-sim)
- [ ] LD2450 angeschlossen (Variante esp32dev)
- [ ] Sensor antwortet (`[LD2450] X Ziel(e)` im Log)
- [ ] `target_count` ändert sich bei Bewegung vor dem Sensor
- [ ] Webseite zeigt Live-Punkt im richtigen Raum

---

## 9. Firmware-Konfiguration im Detail

Die gesamte Konfiguration liegt in einer einzigen Datei:

```
firmware/esp32-ld2450-mqtt/include/config.h
```

> ⚠️ **Diese Datei enthält dein WLAN-Passwort. Sie ist durch `.gitignore` geschützt und wird nicht in Git eingecheckt.** Trotzdem: nicht an fremde Personen weitergeben.

### Alle Konfigurationswerte

```cpp
// ──── WLAN ────────────────────────────────────────────────────────────────
#define WIFI_SSID      "Dein-WLAN-Name"        // Name deines 2,4-GHz-WLANs
#define WIFI_PASSWORD  "dein-wlan-passwort"     // WLAN-Passwort

// ──── MQTT-Broker ─────────────────────────────────────────────────────────
#define MQTT_HOST      "192.168.178.99"         // IP-Adresse des Raspberry Pi
#define MQTT_PORT      1883                     // Standard-MQTT-Port
#define MQTT_CLIENT_ID "hausradar-radar_wohnzimmer"  // Muss pro Sensor eindeutig sein!
#define MQTT_TOPIC     "hausradar/sensor/radar_wohnzimmer/state"  // Topic

// ──── MQTT-Authentifizierung ──────────────────────────────────────────────
#define MQTT_USER      ""                       // Leer = anonym (Standard)
#define MQTT_PASSWORD  ""                       // Nur nötig wenn Mosquitto Auth aktiviert

// ──── Sensor-Identität ────────────────────────────────────────────────────
#define SENSOR_ID   "radar_wohnzimmer"          // Muss zu sensors.json passen!
#define ROOM_ID     "wohnzimmer"                // Muss zu rooms.json passen!

// ──── Sensor-Position (nur für Simulation) ────────────────────────────────
#define SENSOR_X_MM          3000.0f            // X-Position im Raum [mm]
#define SENSOR_Y_MM             0.0f            // Y-Position im Raum [mm]
#define SENSOR_ROTATION_DEG     0.0f            // Ausrichtung in Grad

// ──── Raummaße (nur für Simulation) ──────────────────────────────────────
#define ROOM_WIDTH_MM   6000.0f                 // Raumbreite [mm]
#define ROOM_HEIGHT_MM  4500.0f                 // Raumtiefe [mm]

// ──── UART-Pins ───────────────────────────────────────────────────────────
#define LD2450_RX_PIN   16                      // ESP32 GPIO16 = UART2-RX
#define LD2450_TX_PIN   17                      // ESP32 GPIO17 = UART2-TX
#define LD2450_BAUD     256000                  // Fest eingestellt im Sensor!

// ──── Timing ──────────────────────────────────────────────────────────────
#define PUBLISH_INTERVAL_MS  500                // Sendeintervall in ms (500 = 2×/Sekunde)

// ──── NTP-Zeitserver ──────────────────────────────────────────────────────
#define NTP_SERVER       "pool.ntp.org"         // Für korrekten Timestamp
#define NTP_UTC_OFFSET_S 0                      // Zeitzone (0 = UTC; MEZ = 3600)
```

### Was du anpassen musst (pro Sensor)

| Wert | Was eintragen | Beispiel |
|---|---|---|
| `WIFI_SSID` | Name deines WLANs (2,4 GHz!) | `"Heimnetz-2G"` |
| `WIFI_PASSWORD` | WLAN-Passwort | `"meinPasswort123"` |
| `MQTT_HOST` | IP des Raspberry Pi | `"192.168.178.99"` |
| `MQTT_CLIENT_ID` | Eindeutiger Name, einmal pro Sensor | `"hausradar-radar_kueche"` |
| `MQTT_TOPIC` | Passe `radar_wohnzimmer` an Sensor-ID an | `"hausradar/sensor/radar_kueche/state"` |
| `SENSOR_ID` | Deine Sensor-ID (wie in sensors.json) | `"radar_kueche"` |
| `ROOM_ID` | Raum-ID (wie in rooms.json) | `"kueche"` |

> **Tipp:** Zwei Sensoren dürfen NIE die gleiche `MQTT_CLIENT_ID` haben – sonst kicken sie sich gegenseitig vom Broker.

### PlatformIO Build-Varianten

| Umgebung | Sensor | Wann nutzen |
|---|---|---|
| `esp32dev` | echter LD2450, ESP32 DevKit | Normalbetrieb |
| `esp32dev-sim` | Walker-Simulation, ESP32 DevKit | Testen ohne Sensor |
| `lolin_d32` | echter LD2450, Wemos/LOLIN D32 | Alternative Hardware |
| `lolin_d32-sim` | Walker-Simulation, LOLIN D32 | Testen ohne Sensor |

Flashen:
```bash
cd firmware/esp32-ld2450-mqtt
pio run -e esp32dev -t upload         # echter Sensor
pio run -e esp32dev-sim -t upload     # Simulation
```

---

## 10. MQTT-Test

Bevor du Zeit mit Kalibrierung verbringst: prüfe zuerst, ob Daten ankommen.

### Auf dem Raspberry Pi

```bash
# Alle HausRadar-Nachrichten anzeigen (Strg+C zum Beenden)
mosquitto_sub -h localhost -t 'hausradar/sensor/+/state' -v
```

Wenn jemand sich vor den Sensor bewegt, erscheint alle 0,5 Sekunden eine Zeile:

```
hausradar/sensor/radar_wohnzimmer/state {
  "sensor_id": "radar_wohnzimmer",
  "room_id": "wohnzimmer",
  "timestamp_ms": 1710000123456,
  "target_count": 1,
  "targets": [
    {
      "id": 1,
      "x_mm": 320,
      "y_mm": 1850,
      "speed_mm_s": 0,
      "distance_mm": 1878.5,
      "angle_deg": 9.8
    }
  ]
}
```

### Bedeutung der Felder

| Feld | Beschreibung |
|---|---|
| `sensor_id` | Muss zur `SENSOR_ID` in config.h passen |
| `room_id` | Muss zur `ROOM_ID` in config.h passen |
| `timestamp_ms` | Unix-Timestamp in Millisekunden (NTP oder millis()-Fallback) |
| `target_count` | Anzahl erkannter Ziele (0–3) |
| `targets[].x_mm` | X-Koordinate relativ zum Sensor (positiv = rechts, negativ = links) |
| `targets[].y_mm` | Y-Koordinate = Entfernung vom Sensor in mm (immer ≥ 0) |
| `targets[].speed_mm_s` | Geschwindigkeit (positiv = weg, negativ = heran) |
| `targets[].distance_mm` | Luftlinien-Abstand vom Sensor |
| `targets[].angle_deg` | Winkel relativ zur Sensor-Achse in Grad |

### Testdaten manuell senden (ohne Sensor)

```bash
mosquitto_pub -h localhost \
  -t "hausradar/sensor/radar_wohnzimmer/state" \
  -m '{"sensor_id":"radar_wohnzimmer","room_id":"wohnzimmer","timestamp_ms":1710000000000,"target_count":0,"targets":[]}'
```

---

## 11. Sensorposition im Raum

Die Wahl des Montageorts hat großen Einfluss auf die Erkennungsqualität.

### Gute Positionen

| Wo | Warum gut |
|---|---|
| **An einer Wand, 1,5 – 2,3 m hoch** | Freie Sicht auf den gesamten Raum, Standardmontage |
| **Möglichst mittig an einer Wand** | Gleichmäßige Abdeckung |
| **Blick in den Raum, nicht auf Fenster** | Weniger Störungen durch Autos/Bäume draußen |
| **An y=0-Wand** (oben im Grundriss) | Standard `rotation_deg=0`, einfachste Kalibrierung |
| **Frei von Metallhindernissen** | mmWave wird von Metall stark reflektiert/absorbiert |

### Schlechte Positionen

| Wo | Problem |
|---|---|
| Hinter Metall (Heizung, Schrank) | Signal stark gedämpft oder reflektiert |
| Direkt auf Fenster/Straße gerichtet | Autos, Bäume, Wind → Geisterziele |
| Neben starken Störquellen (Router, Netzteil) | Elektrische Interferenz möglich |
| Direkt auf Ventilator/Vorhänge | Dauerbewegung = dauerhaft erkannte Ziele |
| Zu niedrig (< 1 m) | Haustiere lösen Alarm aus, schlechte Raumabdeckung |
| Stark schräg ohne notierte rotation_deg | Koordinaten stimmen nicht |

### Erfassungsbereich des HLK-LD2450

> **Annahme – prüfe Datenblatt deines Moduls:**
> - Horizontaler Erfassungswinkel: ca. **±60°**
> - Vertikaler Erfassungswinkel: ca. **±40°**
> - Maximale Reichweite: ca. **6 m**
> - Minimale Reichweite: ca. **0,5 m** (zu nah = keine Erkennung)

### Wie viele Sensoren pro Raum?

| Raumgröße | Empfehlung |
|---|---|
| Bis ca. 4 × 5 m | 1 Sensor, mittig an einer Wand |
| 5 × 7 m oder größer | 2 Sensoren, gegenüberliegend |
| L-förmiger Raum | 2 Sensoren, je einen in einem Schenkel |
| Langer Flur (>4 m) | 2 Sensoren an den Enden |

Bei zwei Sensoren im selben Raum: beide bekommen **gleiche `ROOM_ID`**, aber **verschiedene `SENSOR_ID`** und `x_mm`/`y_mm`.

---

## 12. Raum vermessen

Bevor du den Sensor konfigurieren kannst, musst du deinen Raum vermessen.

### Was du messen musst

Nimm ein Maßband und notiere:

| Was | Einheit | Wozu |
|---|---|---|
| **Raumbreite** (von Wand zu Wand) | mm | `width_mm` in rooms.json |
| **Raumtiefe** (von Wand zu Wand) | mm | `height_mm` in rooms.json |
| **Sensorposition X** (Abstand linke Wand → Sensor) | mm | `x_mm` in sensors.json |
| **Sensorposition Y** (Abstand obere Wand → Sensor) | mm | `y_mm` in sensors.json |
| **Montagehöhe** (Boden → Sensor) | mm | `mount_height_mm` in sensors.json |
| Zonenposition (Sofa, Schreibtisch, ...) | mm | `zones` in rooms.json |

> **Tipp:** 1 m = 1000 mm – alle Werte im System sind in **Millimetern**.

### Koordinatensystem des Raums

```
  x=0                        x=width_mm
   │                              │
   ▼                              ▼
  ┌──────────────────────────────┐  ← y=0  (obere Wand)
  │                              │
  │   Raum                       │
  │                              │
  │       ✕ Sensor (x_mm, y_mm)  │
  │                              │
  └──────────────────────────────┘  ← y=height_mm  (untere Wand)
  
  Links-nach-rechts = x
  Oben-nach-unten   = y   (nicht intuitiv, aber Standard in 2D-Grafiken)
```

### Beispiel: Wohnzimmer vermessen

```
Gemessene Werte:
- Breite (links–rechts):  6000 mm
- Tiefe (vorne–hinten):   4500 mm
- Sensor: mittig an der vorderen Wand, 200 mm von der Wand entfernt*
  → x_mm = 3000 (Mitte)
  → y_mm = 0    (vordere Wand = y=0)
- Montagehöhe: 2200 mm
- rotation_deg: 0 (Sensor schaut in den Raum, d.h. in +y-Richtung)

* 200 mm Wandabstand ist vernachlässigbar für die Kalibrierung
  und kann als y_mm=0 konfiguriert werden.
```

### Zonen messen

Zonen sind Bereiche im Raum (Sofa, Schreibtisch, Tür). Messe:
- Abstand von der linken Wand zur **linken Kante** der Zone → `x_mm`
- Abstand von der oberen Wand zur **oberen Kante** der Zone → `y_mm`
- Breite der Zone → `width_mm`
- Tiefe der Zone → `height_mm`

---

## 13. Räume in config/rooms.json eintragen

Öffne `config/rooms.json` und füge deine Räume ein.

### Vollständiges Beispiel: Wohnzimmer

```json
{
  "id": "wohnzimmer",
  "name": "Wohnzimmer",
  "width_mm": 6000,
  "height_mm": 4500,
  "floorplan": {
    "x": 10,
    "y": 10,
    "width": 300,
    "height": 225
  },
  "zones": [
    {
      "id": "sofa",
      "name": "Sofa-Bereich",
      "x_mm": 3500,
      "y_mm": 2500,
      "width_mm": 2000,
      "height_mm": 1500
    },
    {
      "id": "tv",
      "name": "TV-Bereich",
      "x_mm": 500,
      "y_mm": 500,
      "width_mm": 2000,
      "height_mm": 1500
    }
  ]
}
```

### Erklärung aller Felder

| Feld | Typ | Beschreibung |
|---|---|---|
| `id` | String | Eindeutige ID, nur Kleinbuchstaben/Unterstriche, z.B. `"wohnzimmer"` |
| `name` | String | Anzeigename in der Weboberfläche |
| `width_mm` | Zahl | Echte Raumbreite in Millimetern |
| `height_mm` | Zahl | Echte Raumtiefe in Millimetern |
| `floorplan.x` | Zahl | X-Position im SVG-Grundriss (Pixel) |
| `floorplan.y` | Zahl | Y-Position im SVG-Grundriss (Pixel) |
| `floorplan.width` | Zahl | Breite des Raumrechtecks im SVG (Pixel) |
| `floorplan.height` | Zahl | Höhe des Raumrechtecks im SVG (Pixel) |
| `zones[].id` | String | Eindeutige Zonen-ID |
| `zones[].name` | String | Anzeigename der Zone |
| `zones[].x_mm` | Zahl | X-Start der Zone im Raum (linke Kante) |
| `zones[].y_mm` | Zahl | Y-Start der Zone im Raum (obere Kante) |
| `zones[].width_mm` | Zahl | Breite der Zone |
| `zones[].height_mm` | Zahl | Tiefe der Zone |

> **Hinweis zu `floorplan`:** Diese Werte bestimmen, wo der Raum auf der Webseite gezeichnet wird. Räume, die sich im echten Haus nebeneinander befinden, sollten im Grundriss auch nebeneinander liegen. Die Pixel-Werte kannst du frei wählen.

---

## 14. Sensoren in config/sensors.json eintragen

Öffne `config/sensors.json` und trage deinen Sensor ein.

### Vollständiges Beispiel

```json
{
  "id": "radar_wohnzimmer",
  "name": "Radar Wohnzimmer",
  "room_id": "wohnzimmer",
  "x_mm": 3000,
  "y_mm": 0,
  "mount_height_mm": 2200,
  "rotation_deg": 0,
  "enabled": true
}
```

### Erklärung aller Felder

| Feld | Typ | Beschreibung |
|---|---|---|
| `id` | String | **Muss exakt zu `SENSOR_ID` in config.h passen!** z.B. `"radar_wohnzimmer"` |
| `name` | String | Anzeigename in der Weboberfläche |
| `room_id` | String | **Muss exakt zu `id` in rooms.json und `ROOM_ID` in config.h passen!** |
| `x_mm` | Zahl | X-Position des Sensors im Raum-Koordinatensystem [mm] |
| `y_mm` | Zahl | Y-Position des Sensors im Raum-Koordinatensystem [mm] |
| `mount_height_mm` | Zahl | Montagehöhe des Sensors über dem Boden [mm] |
| `rotation_deg` | Zahl | Blickrichtung des Sensors (→ Abschnitt 15) |
| `enabled` | boolean | `true` = Sensor aktiv, `false` = Sensor ignoriert |

> **Wichtig:** Wenn `SENSOR_ID` in config.h und `id` in sensors.json **nicht übereinstimmen**, werden die Daten vom Backend mit Fehler 422 abgelehnt.

---

## 15. Rotation und Ausrichtung kalibrieren

`rotation_deg` ist der wichtigste Wert für die Kalibrierung. Er gibt an, **in welche Raumrichtung der Sensor blickt**.

### Rotationskonvention im Code

Die folgende Tabelle ist **direkt aus dem Code** (`server/app/coordinate_transform.py`) abgeleitet und beschreibt die exakte Bedeutung:

| `rotation_deg` | Sensor blickt in Richtung | Typische Montageposition |
|:--------------:|--------------------------|--------------------------|
| `0°` | Raum-+y (von oben nach unten im Grundriss) | Sensor an der **oberen Wand** (y=0), blickt in den Raum |
| `90°` | Raum-+x (von links nach rechts) | Sensor an der **linken Wand** (x=0), blickt nach rechts |
| `180°` | Raum-−y (von unten nach oben) | Sensor an der **unteren Wand** (y=height_mm), blickt nach oben |
| `270°` | Raum-−x (von rechts nach links) | Sensor an der **rechten Wand** (x=width_mm), blickt nach links |

### Umrechnungsformel (aus coordinate_transform.py)

```
x_raum = sensor_x + xs · cos(θ) + ys · sin(θ)
y_raum = sensor_y − xs · sin(θ) + ys · cos(θ)

θ = rotation_deg (in Grad, Uhrzeigersinn)
xs = Sensor-X (vom Sensor aus: positiv = rechts)
ys = Sensor-Y (Entfernung nach vorne, immer ≥ 0)
```

### Montagetabelle

| Wand (Sensorseite) | `x_mm` | `y_mm` | `rotation_deg` |
|---|---|---|:---:|
| Obere Wand (y=0) | beliebig | `0` | `0` |
| Linke Wand (x=0) | `0` | beliebig | `90` |
| Untere Wand (y=height_mm) | beliebig | `height_mm` | `180` |
| Rechte Wand (x=width_mm) | `width_mm` | beliebig | `270` |

### Visualisierung

```
  rotation_deg = 0            rotation_deg = 90
  (Sensor an oberer Wand)     (Sensor an linker Wand)

  ┌────────[S]────────┐       ┌──[S]──────────────┐
  │         │         │       │   │                │
  │         ▼         │       │   ──►              │
  │                   │       │                    │
  │                   │       │                    │
  └───────────────────┘       └───────────────────┘

  rotation_deg = 180          rotation_deg = 270
  (Sensor an unterer Wand)    (Sensor an rechter Wand)

  ┌───────────────────┐       ┌───────────────[S]──┐
  │                   │       │               │    │
  │         ▲         │       │           ◄──     │
  │         │         │       │                    │
  └────────[S]────────┘       └───────────────────┘
```

---

## 16. Kalibrierung Schritt für Schritt

Kalibrierung = Prüfen ob die Koordinaten auf der Webseite mit der echten Position übereinstimmen.

### Schritt 1: Sensor auf dem Schreibtisch testen

1. LD2450 anschließen, ESP32 flashen (echte Firmware, nicht Simulation)
2. Seriellen Monitor öffnen
3. Die Hand langsam vor den Sensor halten (ca. 50 cm – 1 m Abstand)
4. Prüfen: `[LD2450] 1 Ziel(e)` muss erscheinen
5. Prüfen: auf `mosquitto_sub` auf dem Pi erscheinen Koordinaten

**Wenn kein Ziel erkannt wird:**
- Sensor braucht ~3 Sekunden Aufwärmzeit nach dem Einschalten
- TX/RX-Kabel prüfen (→ vertauscht?)
- Spannung am VCC mit Multimeter prüfen

---

### Schritt 2: Sensor provisorisch im Raum befestigen

- Mit **Klebepads** oder **Klebeband** provisorisch an der geplanten Position befestigen
- Ausrichtung notieren (welche Wand, wie hoch)
- Sensor-ID und Position auf einem Zettel notieren

**Noch NICHT fest verschrauben** – du wirst die Position wahrscheinlich noch anpassen.

---

### Schritt 3: Webseite öffnen

Im Browser:
```
http://hausradar.local:8000
```

Du solltest den Grundriss sehen. Wenn du vor dem Sensor stehst, sollte ein blauer Punkt erscheinen.

---

### Schritt 4: Referenzpunkte ablaufen

Stelle dich nacheinander an **bekannte Positionen** im Raum und prüfe, ob der Punkt auf der Webseite stimmt:

| Position | Was du tust | Was du erwartest |
|---|---|---|
| Direkt vor Sensor, 1 m Abstand | Hinsetzen / Stehen bleiben | Punkt dicht am Sensor |
| Links im Raum, Mitte | Stehen bleiben | Punkt links auf der Karte |
| Rechts im Raum, Mitte | Stehen bleiben | Punkt rechts auf der Karte |
| Hinten im Raum | Stehen bleiben | Punkt hinten auf der Karte |
| Sofa/Zone | Hinsetzen | `zone_id` sollte auf Sofa zeigen |

**Typische Fehler:**

| Symptom | Mögliche Ursache |
|---|---|
| Punkt spiegelt links/rechts | `rotation_deg` um 0/180° oder Vorzeichen prüfen |
| Punkt spiegelt vorne/hinten | `rotation_deg` um 90/270° prüfen |
| Alles gleichmäßig verschoben | `x_mm`/`y_mm` des Sensors anpassen |
| Punkt außerhalb des Raums | Sensorposition falsch ODER Raummaße falsch |
| Skalierung falsch (zu groß/klein) | `width_mm`/`height_mm` in rooms.json prüfen |

---

### Schritt 5: Sensorposition korrigieren

Ändere `config/sensors.json` und starte das Backend neu:

```bash
# Backend neustarten (auf dem Pi):
sudo systemctl restart hausradar
```

Konfigurationsänderungen in `rooms.json` und `sensors.json` erfordern einen Neustart.

---

### Schritt 6: Zonen prüfen

Bewege dich in die definierten Zonen und prüfe in der Webseite, ob die richtige Zone erkannt wird:

```bash
# Live-Daten mit Zone-Info anzeigen:
curl http://localhost:8000/api/live | python3 -m json.tool
```

Suche nach `"zone_id"` im Ergebnis – dieser Wert muss zur Zone passen, in der du dich befindest.

---

### Schritt 7: Finale Montage

Erst wenn alle Punkte stimmen:
- [ ] Sensor **fest montieren** (Schrauben oder dauerhafte Klebepads)
- [ ] Kabel **sichern** (Kabelbinder, nicht straff gespannt)
- [ ] Gehäuse schließen
- [ ] Sensor-ID auf dem Gehäuse mit Aufkleber oder Edding notieren
- [ ] Position in deinen Notizen/Fotos dokumentieren

---

## 17. Typische Fehlerbilder und Lösungen

### Hardware-Probleme

| Problem | Mögliche Ursache | Lösung |
|---|---|---|
| ESP32 startet nicht | Schlechtes USB-Kabel | Anderes Kabel probieren (Datenkabel, nicht Ladekabel) |
| ESP32 startet nicht | Kurzschluss durch Sensor | Sensor abziehen, neu testen |
| ESP32 startet nicht | Zu schwaches Netzteil | Netzteil mit mind. 1A verwenden |
| Kein Text im seriellen Monitor | Falscher COM-Port | In PlatformIO: korrekten Port wählen |
| Kein Text im seriellen Monitor | Falscher Monitor-Speed | Muss 115200 Baud sein |
| Sensor heiß oder riecht | Falsche Spannung / Polung | Sofort trennen, Anschlüsse prüfen |

### WLAN-Probleme

| Problem | Mögliche Ursache | Lösung |
|---|---|---|
| `[WiFi] Verbindung fehlgeschlagen` | Falsche SSID oder Passwort | `config.h` prüfen |
| `[WiFi] Verbindung fehlgeschlagen` | 5-GHz-only-WLAN | ESP32 unterstützt nur **2,4 GHz** |
| `[WiFi] Verbindung fehlgeschlagen` | Schlechtes Signal | Router näher platzieren oder WLAN-Repeater |
| Verbindung bricht immer wieder ab | Wackelnde Verbindung | Signalstärke prüfen; WLAN-Kanal wechseln |

### MQTT-Probleme

| Problem | Mögliche Ursache | Lösung |
|---|---|---|
| `[MQTT] Fehlgeschlagen (state=-2)` | Falsche Pi-IP in `MQTT_HOST` | IP des Pi erneut herausfinden: `hostname -I` |
| `[MQTT] Fehlgeschlagen (state=5)` | Authentifizierungsfehler | `MQTT_USER`/`MQTT_PASSWORD` prüfen |
| Mosquitto läuft nicht | Service gestoppt | `sudo systemctl start mosquitto` |
| MQTT verbindet, Daten kommen aber nicht an | Falsches Topic | `MQTT_TOPIC` in config.h prüfen |
| ESP32 verbindet sich und trennt sofort | Zwei Sensoren gleiche `MQTT_CLIENT_ID` | Jeder Sensor braucht eigene Client-ID |

### Sensordaten-Probleme

| Problem | Mögliche Ursache | Lösung |
|---|---|---|
| `[LD2450] 0 Ziel(e)` obwohl Bewegung | TX/RX vertauscht | Kabel tauschen: TX↔RX |
| `[LD2450] 0 Ziel(e)` obwohl Bewegung | Sensor bekommt keinen Strom | Spannung am VCC messen |
| `[LD2450] 0 Ziel(e)` obwohl Bewegung | Falsche GPIO-Pins | `LD2450_RX_PIN` in config.h prüfen |
| `[LD2450] 0 Ziel(e)` obwohl Bewegung | Sensor braucht Aufwärmzeit | 3–5 Sekunden nach dem Einschalten warten |
| Baudrate-Fehler im Log | Falsche Baudrate | LD2450 ist **256000 Baud**, nicht änderbar |
| Sensor erkennt durch Wand | mmWave geht durch dünne Materialien | Ausrichtung ändern; keine Wände zwischen Sensor und Zielraum |

### Koordinaten-Probleme

| Problem | Mögliche Ursache | Lösung |
|---|---|---|
| Punkt ist links-rechts gespiegelt | `rotation_deg` falsch | Probe: `rotation_deg=0` testen, dann justieren |
| Punkt ist vorne-hinten gespiegelt | `rotation_deg` falsch | 180° zur aktuellen Rotation addieren |
| Punkt ist gleichmäßig verschoben | `x_mm`/`y_mm` in sensors.json falsch | Sensorposition neu messen |
| Punkt landet außerhalb Raumrechteck | Raummaße zu klein | `width_mm`/`height_mm` in rooms.json prüfen |
| Zone wird nie erkannt | Zonen-Koordinaten falsch | Zonenposition in rooms.json überprüfen |
| `422 Unbekannter Sensor` im Log | `sensor_id` passt nicht | `SENSOR_ID` in config.h muss exakt `id` in sensors.json entsprechen |
| Geisterziele (Punkt ohne Person) | Ventilator, Vorhänge, Straße | Montageort ändern; Sensor nicht auf Fenster/Heizung richten |
| Sensor erkennt Haustiere | Sensor zu niedrig | Höher montieren; `mount_height_mm` erhöhen |

### Webseite-Probleme

| Problem | Mögliche Ursache | Lösung |
|---|---|---|
| Webseite nicht erreichbar | Backend nicht gestartet | `systemctl status hausradar` auf dem Pi |
| Kein Live-Punkt auf Grundriss | WebSocket getrennt | Badge oben rechts prüfen; Seite neu laden |
| Kein Live-Punkt auf Grundriss | Sensor offline | `curl http://localhost:8000/api/live` prüfen |
| Raum erscheint nicht | Raum nicht in rooms.json | Config prüfen, Backend neu starten |

---

## 18. Montage im Gehäuse

### Materialempfehlung

- **Kunststoffgehäuse** jeder Art ist geeignet (Schalterdose, kleine Projektbox, 3D-Druck)
- **Metall** vermeiden – dämpft das mmWave-Signal stark
- Auch lackiertes Metall (z.B. Heizungsverkleidung) kann problematisch sein

### Aufbau im Gehäuse

```
┌────────────────────────────────┐
│  ┌──────────┐  ┌─────────────┐ │  ← Kunststoff-Gehäuse
│  │ LD2450   │  │   ESP32     │ │
│  │          │  │             │ │
│  │ Sensor   │  │  [USB-C]──── ──►  USB-Kabel raus
│  │ vorne    │  │             │ │
│  └──────────┘  └─────────────┘ │
│       │              │         │
│    Dupont-Kabel verbinden      │
└────────────────────────────────┘
        │
        ▼  Sensor-Fläche nach vorne (in den Raum)
```

### Wichtige Hinweise

- **Sensor-Fläche nach vorne** ausrichten, nicht verdeckt
- **Lüftungschlitze** für den ESP32 vorsehen (Wärmeabfuhr)
- **USB-C-Öffnung** zugänglich lassen (Wartung, Neustarts)
- **Kabelzugentlastung** einplanen – ein losgerissener Dupont-Stecker nach Monaten ist ärgerlich
- Sensor-ID und Raum-Name **außen auf dem Gehäuse** notieren (Aufkleber oder Edding)

### 3D-Druck-Hinweise

> **Annahme:** Maße müssen am eigenen Modul gemessen werden.

- Kunststofffilament (PLA, PETG) ist vollständig durchlässig für mmWave-Signale
- Wandstärke: 1–2 mm reicht; dickere Wände kaum Einfluss
- Achte auf ausreichend Platz für Dupont-Kabel ohne Knick
- Öffnung für LD2450-Frontseite vorsehen oder Gehäuse ohne Abdeckung vorne

---

## 19. Mehrere Sensoren in einem Raum

Manchmal reicht ein Sensor nicht aus.

### Wann zwei Sensoren sinnvoll sind

- Raum größer als ca. 4 × 6 m
- L-förmiger oder verwinkelt geschnittener Raum
- Große Möbel erzeugen tote Winkel
- Langer Flur (>4 m)

### Konfiguration für zwei Sensoren im selben Raum

**config/sensors.json:**
```json
[
  {
    "id": "radar_wohnzimmer_ost",
    "name": "Radar Wohnzimmer Ost",
    "room_id": "wohnzimmer",
    "x_mm": 500,
    "y_mm": 0,
    "mount_height_mm": 2200,
    "rotation_deg": 0,
    "enabled": true
  },
  {
    "id": "radar_wohnzimmer_west",
    "name": "Radar Wohnzimmer West",
    "room_id": "wohnzimmer",
    "x_mm": 5500,
    "y_mm": 0,
    "mount_height_mm": 2200,
    "rotation_deg": 0,
    "enabled": true
  }
]
```

**config.h für jeden ESP32 anpassen:**
```cpp
// ESP32 Nr. 1:
#define SENSOR_ID    "radar_wohnzimmer_ost"
#define MQTT_CLIENT_ID "hausradar-wohnzimmer-ost"
#define MQTT_TOPIC   "hausradar/sensor/radar_wohnzimmer_ost/state"

// ESP32 Nr. 2:
#define SENSOR_ID    "radar_wohnzimmer_west"
#define MQTT_CLIENT_ID "hausradar-wohnzimmer-west"
#define MQTT_TOPIC   "hausradar/sensor/radar_wohnzimmer_west/state"
```

**Wichtige Regeln:**
- Gleiche `room_id` ist erlaubt und gewollt
- Verschiedene `id`, `MQTT_CLIENT_ID` und `MQTT_TOPIC` sind Pflicht
- Jeder Sensor bekommt seine eigene `x_mm`/`y_mm`-Position

Das Backend verarbeitet mehrere Sensoren pro Raum gleichzeitig – beide Punkte erscheinen auf dem Grundriss.

---

## 20. Datenschutz-Hinweise zur Hardware

mmWave-Radar macht **keine Fotos** und **keine Videoaufnahmen**. Trotzdem sind einige Hinweise wichtig:

### Was erfasst wird

- Bewegungen und Positionen von Personen im Raum
- Über Zeit entstehen **Aufenthaltsmuster** (wann, wo, wie lange)
- Diese Muster können sehr sensibel sein (Schlafzeiten, Routinen, Abwesenheit)

### Empfehlungen

| Empfehlung | Warum |
|---|---|
| **Alle Haushaltsmitglieder informieren** | Jeder sollte wissen, dass Bewegungen erfasst werden |
| **Besucher informieren** | Gastbereiche sparsam mit Sensoren ausstatten |
| **Keine Sensoren in Schlafräumen** ohne explizite Zustimmung aller Personen | Schlafmuster sind besonders sensibel |
| **Retention begrenzen** (`retention_days: 7` statt 30) | Weniger Daten = weniger Risiko |
| **Daten lokal halten** | Kein Cloud-Dienst nötig; HausRadar ist vollständig offline |
| **Zugang zum Pi absichern** | Starkes SSH-Passwort; API-Key aktivieren (→ `docs/security-hardening.md`) |

---

## 21. Abschluss-Checkliste pro Raum

Nutze diese Checkliste für jeden neuen Raum:

### Vorbereitung
- [ ] Raum vermessen (Breite, Tiefe, alle Maße in mm)
- [ ] Sensorposition bestimmt (X, Y, Höhe, Ausrichtung)
- [ ] Raum-ID und Sensor-ID festgelegt

### Konfiguration
- [ ] Raum in `config/rooms.json` eingetragen
- [ ] Zonen gemessen und eingetragen
- [ ] Sensor in `config/sensors.json` eingetragen (x_mm, y_mm, rotation_deg)
- [ ] `config.h` für diesen ESP32 angepasst (SENSOR_ID, ROOM_ID, MQTT_*,  WIFI_*)

### Hardware
- [ ] LD2450 korrekt an ESP32 angeschlossen (VCC, GND, TX→GPIO16, RX→GPIO17)
- [ ] Stromversorgung korrekt (Spannung gemessen?)
- [ ] Firmware geflasht (`pio run -e esp32dev -t upload`)

### Test
- [ ] WLAN-Verbindung funktioniert (IP im seriellen Monitor)
- [ ] MQTT-Verbindung funktioniert (`[MQTT] Verbunden.`)
- [ ] `[LD2450] X Ziel(e)` erscheint bei Bewegung
- [ ] MQTT-Daten auf Pi sichtbar (`mosquitto_sub`)
- [ ] Live-Punkt erscheint auf der Webseite
- [ ] Referenzpunkte abgelaufen und Koordinaten stimmen
- [ ] `rotation_deg` geprüft (links/rechts, vorne/hinten korrekt)
- [ ] Zonen erkannt (`zone_id` stimmt)

### Finale Montage
- [ ] Sensor fest montiert
- [ ] Kabel gesichert (Kabelbinder, Zugentlastung)
- [ ] Gehäuse geschlossen
- [ ] Sensor-ID außen auf Gehäuse notiert
- [ ] Position in eigener Dokumentation/Foto festgehalten
- [ ] Backend nach Konfigurationsänderung neugestartet

---

## 22. Kurzanleitung für den ersten Raum

**Für alle die es kurz brauchen – alle Details oben.**

```
1.  Raspberry Pi einrichten           → docs/setup-pi-zero-2.md
2.  config.h anpassen                 → firmware/esp32-ld2450-mqtt/include/config.h
3.  Simulation-Firmware flashen       → pio run -e esp32dev-sim -t upload
4.  Webseite testen                   → http://hausradar.local:8000
5.  Raum vermessen                    → Maßband, alles in mm
6.  rooms.json anpassen               → config/rooms.json
7.  sensors.json anpassen             → config/sensors.json
8.  Backend neustarten                → sudo systemctl restart hausradar
9.  LD2450 anschließen                → TX→GPIO16, RX→GPIO17, GND, VCC
10. Echte Firmware flashen            → pio run -e esp32dev -t upload
11. MQTT prüfen                       → mosquitto_sub -h localhost -t 'hausradar/#' -v
12. Webseite: durch Raum laufen       → Punkt auf Grundriss sehen?
13. rotation_deg kalibrieren          → links/rechts/vorne/hinten stimmt?
14. Sensor fest montieren             → erst nach erfolgreichem Test!
```

---

## Anhang: MQTT-Topics Referenz

| Topic | Richtung | Beschreibung |
|---|---|---|
| `hausradar/sensor/{sensor_id}/state` | ESP32 → Pi | Bewegungsdaten, alle 500 ms |

Alle Topics beginnen mit `hausradar/sensor/` gefolgt von der Sensor-ID aus `config.h`.

> **Hinweis:** Ein `availability`-Topic (LWT) ist in `docs/mqtt-topics.md` beschrieben, aber in der aktuellen Firmware (`main.cpp`) **nicht implementiert**. Der Backend-Server erkennt Sensor-Ausfälle über das `sensor_offline_timeout_seconds`-Timeout in `config/settings.json`.

---

## Anhang: Schnellreferenz Koordinatensystem

```
Raum-Koordinaten:
  Ursprung = linke obere Ecke
  +x = nach rechts
  +y = nach unten (Richtung Raumtiefe)

Sensor-Koordinaten (LD2450-Ausgabe):
  Ursprung = Sensor selbst
  +x = rechts vom Sensor (beim Blick in den Raum)
  −x = links vom Sensor
  +y = nach vorne (Entfernung) – immer ≥ 0

rotation_deg (Uhrzeigersinn):
  0°  → Sensor schaut nach unten im Grundriss (+y-Richtung)
  90° → Sensor schaut nach rechts im Grundriss (+x-Richtung)
```

Detaillierte Beschreibung: `docs/coordinate-system.md`
