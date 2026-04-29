"""
Koordinatenumrechnung für HausRadar.

Koordinatensysteme
------------------
Sensor-Koordinaten (LD2450-Ausgabe):
    Ursprung = Sensor selbst
    +x = rechts vom Sensor aus gesehen
    +y = nach vorne (Entfernung)

Raum-Koordinaten:
    Ursprung = linke obere Ecke des Raums
    +x = nach rechts  (0 … width_mm)
    +y = nach unten   (0 … height_mm)

Grundriss-Koordinaten (SVG-Pixel):
    Entsprechen direkt den floorplan-Feldern in rooms.json:
    fp["x"], fp["y"] = linke obere Ecke des Raumrechtecks im SVG
    fp["width"], fp["height"] = Breite/Höhe des Raumrechtecks im SVG

Rotationskonvention (rotation_deg):
    0°   → Sensor zeigt in Raum-+y-Richtung (Standardmontage an y=0-Wand)
    90°  → Sensor zeigt in Raum-+x-Richtung (Montage an x=0-Wand)
    180° → Sensor zeigt in Raum–-y-Richtung (Montage an Gegenwand)
    270° → Sensor zeigt in Raum–-x-Richtung (Montage an x=width-Wand)
    Drehrichtung: Uhrzeigersinn
"""

import math
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def transform_sensor_to_room(sensor_config: dict, target: dict) -> dict:
    """Rechnet Sensor-lokale Zielkoordinaten in Raum-Koordinaten um.

    Eingabe:
        sensor_config  – ein Sensorobjekt aus sensors.json
        target         – dict mit Feldern x_mm (int/float) und y_mm (int/float)

    Optionale Felder in sensor_config:
        flip_x  – bool (default false): spiegelt die X-Achse des Sensors.
                  Nützlich wenn links/rechts auf der Karte vertauscht ist,
                  ohne dass der Sensor physisch gedreht werden muss.

    Rückgabe:
        {"x_mm": float, "y_mm": float}  – Position im Raum-Koordinatensystem
    """
    angle_rad = math.radians(sensor_config["rotation_deg"])
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    xs = float(target["x_mm"])
    ys = float(target["y_mm"])

    # Optional: X-Achse spiegeln (links/rechts-Korrektur)
    if sensor_config.get("flip_x", False):
        xs = -xs

    # Uhrzeigersinn-Rotation: Sensorachsen im Raumrahmen
    # sensor +x_s  →  (cos θ, –sin θ)  im Raum
    # sensor +y_s  →  (sin θ,  cos θ)  im Raum
    x_rel = xs * cos_a + ys * sin_a
    y_rel = -xs * sin_a + ys * cos_a

    return {
        "x_mm": sensor_config["x_mm"] + x_rel,
        "y_mm": sensor_config["y_mm"] + y_rel,
    }


def transform_room_to_floorplan(room_config: dict,
                                room_x_mm: float,
                                room_y_mm: float) -> dict:
    """Rechnet Raum-Koordinaten in SVG-Grundriss-Koordinaten um.

    Die Skalierung ergibt sich aus dem Verhältnis der Raum-Abmessungen
    zur Pixelgröße des Raumrechtecks im Grundriss.

    Rückgabe:
        {"x": float, "y": float}  – Pixelkoordinaten im SVG
    """
    fp = room_config["floorplan"]
    scale_x = fp["width"]  / room_config["width_mm"]
    scale_y = fp["height"] / room_config["height_mm"]

    return {
        "x": fp["x"] + room_x_mm * scale_x,
        "y": fp["y"] + room_y_mm * scale_y,
    }


def is_target_inside_room(room_config: dict,
                          room_x_mm: float,
                          room_y_mm: float) -> bool:
    """Gibt True zurück, wenn der Punkt innerhalb der Raumgrenzen liegt."""
    return (
        0.0 <= room_x_mm <= room_config["width_mm"]
        and 0.0 <= room_y_mm <= room_config["height_mm"]
    )


def detect_zone(room_config: dict,
                room_x_mm: float,
                room_y_mm: float) -> Optional[str]:
    """Gibt die id der ersten passenden Zone zurück, sonst None.

    Zonen werden in der Reihenfolge aus rooms.json geprüft.
    Die erste Zone, in deren Rechteck der Punkt liegt, gewinnt.
    """
    for zone in room_config.get("zones", []):
        zx = zone.get("x_mm", 0)
        zy = zone.get("y_mm", 0)
        zw = zone.get("width_mm", 0)
        zh = zone.get("height_mm", 0)
        if zx <= room_x_mm <= zx + zw and zy <= room_y_mm <= zy + zh:
            return zone["id"]
    return None


def full_transform(sensor_config: dict,
                   room_config: dict,
                   target: dict) -> dict:
    """Kombinierter Durchlauf: Sensor → Raum → Grundriss + Zonen-Erkennung.

    Rückgabe:
        {
          "room_x_mm": float,
          "room_y_mm": float,
          "floorplan_x": float,
          "floorplan_y": float,
          "inside_room": bool,
          "zone_id": str | None,
        }
    """
    room_pos = transform_sensor_to_room(sensor_config, target)
    rx, ry = room_pos["x_mm"], room_pos["y_mm"]

    inside = is_target_inside_room(room_config, rx, ry)
    zone_id = detect_zone(room_config, rx, ry) if inside else None

    fp_pos = transform_room_to_floorplan(room_config, rx, ry)

    if not inside:
        logger.debug(
            "Sensor '%s': Ziel außerhalb Raum '%s' bei (%.0f, %.0f) mm",
            sensor_config.get("id"), room_config.get("id"), rx, ry,
        )

    return {
        "room_x_mm":  rx,
        "room_y_mm":  ry,
        "floorplan_x": fp_pos["x"],
        "floorplan_y": fp_pos["y"],
        "inside_room": inside,
        "zone_id":    zone_id,
    }
