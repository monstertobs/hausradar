# HausRadar – Koordinatensystem

> **Praktische Kalibrieranleitung** (wie rotation_deg einstellen): [docs/hardware-setup.md → Abschnitt 15–16](hardware-setup.md)

## Überblick

Im System gibt es drei verschiedene Koordinatenräume, zwischen denen umgerechnet wird:

```
[Sensor-Koordinaten]  →  [Raum-Koordinaten]  →  [Grundriss-Koordinaten]
  (LD2450-Ausgabe)        (mm im Raum)           (Pixel im SVG)
```

---

## 1. Sensor-Koordinaten (LD2450-Ausgabe)

Der HLK-LD2450 liefert Zielkoordinaten **relativ zum Sensor**:

| Achse   | Richtung                                         |
|---------|--------------------------------------------------|
| `x_mm`  | positiv = rechts vom Sensor, negativ = links     |
| `y_mm`  | positiv = nach vorne (Entfernung vom Sensor)     |

**Beispiel:** Ein Ziel bei `x=500, y=2000` befindet sich 2 m geradeaus und 50 cm rechts.

---

## 2. Raum-Koordinaten

Das Raum-Koordinatensystem hat seinen Ursprung in der **linken oberen Ecke** des Raums:

```
(0, 0) ──────────────► x  (0 … width_mm)
  │
  │
  ▼
  y  (0 … height_mm)
```

Wände liegen bei:
- Linke Wand:   `x = 0`
- Rechte Wand:  `x = width_mm`
- Obere Wand:   `y = 0`
- Untere Wand:  `y = height_mm`

---

## 3. Rotationskonvention (`rotation_deg`)

`rotation_deg` gibt die **Drehung des Sensors im Uhrzeigersinn** gegenüber der Standardausrichtung an:

| `rotation_deg` | Sensor zeigt in Richtung |
|:--------------:|--------------------------|
| 0°             | Raum-+y (von oben nach unten → typisch für Montage an y=0-Wand) |
| 90°            | Raum-+x (von links nach rechts → typisch für Montage an x=0-Wand) |
| 180°           | Raum-−y (von unten nach oben → Montage an y=height-Wand) |
| 270°           | Raum-−x (von rechts nach links → Montage an x=width-Wand) |

**Standard-Montage** (alle konfigurierten Sensoren): `y_mm = 0`, `rotation_deg = 0`  
Der Sensor hängt an der oberen Wand und blickt in den Raum hinein.

---

## 4. Umrechnungsformel: Sensor → Raum

Sei `θ = rotation_deg` (in Grad, umgerechnet in Bogenmass), `xs`/`ys` die Sensor-Koordinaten und `sx`/`sy` die Montageposition des Sensors im Raum:

```
x_raum = sx  +  xs·cos(θ)  +  ys·sin(θ)
y_raum = sy  −  xs·sin(θ)  +  ys·cos(θ)
```

**Verifikation θ = 0°:**
```
x_raum = sx + xs·1 + ys·0 = sx + xs  ✓
y_raum = sy − xs·0 + ys·1 = sy + ys  ✓
```

**Verifikation θ = 90°:**  
Sensor zeigt in +x-Richtung. Ein Ziel geradeaus (xs=0, ys=2000):
```
x_raum = sx + 0·0 + 2000·1 = sx + 2000  ✓  (2 m nach rechts)
y_raum = sy − 0·1 + 2000·0 = sy         ✓  (gleiche Höhe)
```

---

## 5. Umrechnungsformel: Raum → Grundriss (SVG-Pixel)

Aus `rooms.json` entnehmen wir für jeden Raum:
- `floorplan.x`, `floorplan.y` – linke obere Ecke des Raumrechtecks im SVG
- `floorplan.width`, `floorplan.height` – Größe des Raumrechtecks in Pixeln

Der Maßstab ergibt sich automatisch:

```
scale_x = floorplan.width  / width_mm
scale_y = floorplan.height / height_mm

svg_x = floorplan.x  +  room_x_mm · scale_x
svg_y = floorplan.y  +  room_y_mm · scale_y
```

**Beispiel** (Wohnzimmer: 6000×4500 mm → 300×225 px):
- Raum-Punkt (3000, 2250) → SVG (10 + 150, 10 + 112,5) = (160, 122,5)

---

## 6. Zonen-Erkennung

Zonen sind Rechtecke **im Raum-Koordinatensystem** (nicht SVG). Ein Punkt `(rx, ry)` liegt in einer Zone, wenn:

```
zone.x_mm ≤ rx ≤ zone.x_mm + zone.width_mm
zone.y_mm ≤ ry ≤ zone.y_mm + zone.height_mm
```

Sind mehrere Zonen konfiguriert, gewinnt die **erste** in der Liste (Reihenfolge aus `rooms.json`).

---

## 7. Außerhalb-des-Raums-Behandlung

Liefert ein Sensor Koordinaten außerhalb der Raumgrenzen (`x < 0`, `x > width_mm`, `y < 0`, `y > height_mm`):
- `is_target_inside_room()` gibt `False` zurück
- `detect_zone()` wird nicht aufgerufen (gibt `None` zurück)
- Die Grundriss-Koordinaten werden trotzdem berechnet (können außerhalb des SVG-Rechtecks liegen)
- Das Frontend filtert solche Punkte heraus oder zeichnet sie anders

---

## 8. Python-API

```python
from app.coordinate_transform import (
    transform_sensor_to_room,
    transform_room_to_floorplan,
    is_target_inside_room,
    detect_zone,
    full_transform,       # kombinierter Durchlauf
)

sensor = {"id": "radar_wohnzimmer", "x_mm": 3000, "y_mm": 0,
          "rotation_deg": 0, ...}
room   = rooms_dict["wohnzimmer"]
target = {"x_mm": 420, "y_mm": 2500}

# Einzel-Schritte
raum_pos = transform_sensor_to_room(sensor, target)
fp_pos   = transform_room_to_floorplan(room, raum_pos["x_mm"], raum_pos["y_mm"])
inside   = is_target_inside_room(room, raum_pos["x_mm"], raum_pos["y_mm"])
zone     = detect_zone(room, raum_pos["x_mm"], raum_pos["y_mm"])

# Oder alles auf einmal:
result = full_transform(sensor, room, target)
# result = {
#   "room_x_mm":  3420.0,
#   "room_y_mm":  2500.0,
#   "floorplan_x": 181.0,
#   "floorplan_y": 135.0,
#   "inside_room": True,
#   "zone_id":    "sofa",
# }
```

---

## 9. Montage-Empfehlungen

| Wand           | `x_mm`        | `y_mm`     | `rotation_deg` |
|----------------|---------------|------------|:--------------:|
| Oben (y=0)     | beliebig      | 0          | 0°             |
| Links (x=0)    | 0             | beliebig   | 90°            |
| Unten          | beliebig      | height_mm  | 180°           |
| Rechts         | width_mm      | beliebig   | 270°           |

Der Sensor sollte möglichst **zentral** und **hoch** (≥ 2 m) montiert werden, um den gesamten Raum abzudecken.
