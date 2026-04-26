# HausRadar – Hardware-Übersicht

> Ausführliche Aufbau- und Kalibrieranleitung: **[docs/hardware-setup.md](hardware-setup.md)**

---

## Stückliste (pro Raum)

| Komponente | Beschreibung |
|---|---|
| **ESP32 Dev Board** | Mikrocontroller mit WLAN (z.B. AZ-Delivery ESP32 DevKitC v4, LOLIN D32) |
| **HLK-LD2450** | 24-GHz-mmWave-Radarsensor |
| **Netzteil 5 V / 1–2 A** | USB-C oder direkt; 2 A empfohlen |
| **Dupont-Kabel** | 4× Buchse–Buchse zum Verbinden |

## Zentrale Einheit

| Komponente | Beschreibung |
|---|---|
| **Raspberry Pi Zero 2 W** | Hauptserver mit WLAN |
| **MicroSD-Karte ≥ 8 GB** | A1-Rating empfohlen (z.B. SanDisk Endurance) |
| **Netzteil 5 V / 2,5 A** | Micro-USB; offizielles Pi-Netzteil bevorzugt |

---

## Verkabelung ESP32 ↔ HLK-LD2450

```
HLK-LD2450          ESP32 Dev Board
─────────────       ───────────────────
VCC  ──────────►    3V3 (oder VIN/5V)*
GND  ──────────►    GND
TX   ──────────►    GPIO16 (UART2-RX)    ← Sensor sendet Daten
RX   ──────────►    GPIO17 (UART2-TX)    ← ESP32 sendet (optional)
```

> **\* Annahme – prüfe Datenblatt deines Moduls:**
> Einige LD2450-Breakout-Boards laufen auf **3,3 V**, andere auf **5 V**.
> Die UART-Leitungen (TX/RX) sind immer 3,3-V-kompatibel.

**Baudrate:** 256.000 Baud (fest im Sensor eingestellt, nicht änderbar)  
**UART:** Hardware-Serial UART2 des ESP32  
**Pins konfigurierbar** in `firmware/esp32-ld2450-mqtt/include/config.h`:
```cpp
#define LD2450_RX_PIN  16   // ESP32 GPIO16 empfängt Sensor-TX
#define LD2450_TX_PIN  17   // ESP32 GPIO17 sendet an Sensor-RX
#define LD2450_BAUD    256000
```

---

## HLK-LD2450 Frame-Protokoll

Jeder Frame ist **30 Bytes** lang:

| Bytes | Inhalt |
|---|---|
| 0–3 | Frame-Header: `AA FF 03 00` |
| 4–11 | Ziel 1 (8 Bytes) |
| 12–19 | Ziel 2 (8 Bytes) |
| 20–27 | Ziel 3 (8 Bytes) |
| 28–29 | Frame-Ende: `55 CC` |

Pro Ziel (8 Bytes, little-endian):

| Bytes | Inhalt | Kodierung |
|---|---|---|
| 0–1 | X-Koordinate [mm] | Bit 15=0 → positiv (rechts); Bit 15=1 → negativ (links) |
| 2–3 | Y-Koordinate [mm] | gleiche Kodierung; in der Praxis immer ≥ 0 (Entfernung) |
| 4–5 | Geschwindigkeit [mm/s] | positiv = weg vom Sensor; negativ = auf Sensor zu |
| 6–7 | Auflösung/Gate [mm] | unsigned, Messgate-Breite |

Leerer Slot: X=0 AND Y=0 AND Speed=0

Maximum: **3 Ziele gleichzeitig** (Hardware-Limit des LD2450)

---

## Montagetipps

- Sensor möglichst **zentral und hoch** (1,5–2,3 m) an einer Wand montieren
- **Erfassungsbereich** (Annahme – prüfe Datenblatt): ca. ±60° horizontal, ±40° vertikal
- **Maximale Reichweite**: ca. 6 m (Annahme – prüfe Datenblatt)
- Keine Abdeckung mit Metall oder Metallfarbe
- Nicht auf Fenster/Straße richten (Geisterziele)
- `rotation_deg` in sensors.json korrekt eintragen (→ `docs/coordinate-system.md`)

---

## Weitere Dokumentation

| Dokument | Inhalt |
|---|---|
| [hardware-setup.md](hardware-setup.md) | Vollständige Aufbau- und Kalibrieranleitung |
| [coordinate-system.md](coordinate-system.md) | Koordinatensystem, rotation_deg, Formeln |
| [setup-pi-zero-2.md](setup-pi-zero-2.md) | Raspberry Pi einrichten |
| [mqtt-topics.md](mqtt-topics.md) | MQTT-Topics und Payload-Format |
| [troubleshooting.md](troubleshooting.md) | Fehlerbehebung |
