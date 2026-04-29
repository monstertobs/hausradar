"""
Kalibrierungs-Engine für HausRadar.

Verwaltet In-Memory-Sessions und berechnet Raummaße + Sensorposition
aus gemessenen Eckpunkten sowie Möbelpositionen aus je zwei Eckpunkten.

Session-Lebenszyklus:
  1. create_session(sensor_id, room_id)           → session_id
  2. mark_corner(session_id, label, x_mm, y_mm)   [4 × Raumecken]
  3. compute_room(session_id)                      → Raummaße
  4. add_furniture / mark_furniture_corner /
     compute_furniture_pos                         [optional, wiederholbar]
  5. delete_session(session_id)

Ecken-Bezeichnungen (Sensor an y=0-Wand, blickt in +y-Richtung):
  back_left   – weit weg, links   (höchstes ys, kleinstes xs)
  back_right  – weit weg, rechts  (höchstes ys, größtes xs)
  front_right – nahe, rechts      (~1 m von der Wand entfernt, rechts)
  front_left  – nahe, links       (~1 m von der Wand entfernt, links)

Alle x/y-Koordinaten die übergeben werden sind rohe Sensor-Koordinaten
(xs, ys) – nicht Raumkoordinaten.
"""

import math
import time
import uuid
from typing import Optional

_sessions: dict = {}

CORNER_SEQUENCE = ["back_left", "back_right", "front_right", "front_left"]

CORNER_DISPLAY = {
    "back_left":   {
        "de":   "Hinten Links",
        "hint": "Geh in die hintere linke Ecke des Raums (weit vom Sensor entfernt)",
        "icon": "↖",
    },
    "back_right":  {
        "de":   "Hinten Rechts",
        "hint": "Geh in die hintere rechte Ecke des Raums (weit vom Sensor entfernt)",
        "icon": "↗",
    },
    "front_right": {
        "de":   "Vorne Rechts",
        "hint": "Geh in die vordere rechte Ecke – steh ca. 1 m von der Sensor-Wand entfernt",
        "icon": "↘",
    },
    "front_left":  {
        "de":   "Vorne Links",
        "hint": "Geh in die vordere linke Ecke – steh ca. 1 m von der Sensor-Wand entfernt",
        "icon": "↙",
    },
}

FURNITURE_TYPES = {
    "sofa":        {"de": "Sofa/Couch",     "color": "#92400e"},
    "chair":       {"de": "Stuhl/Sessel",   "color": "#78350f"},
    "table":       {"de": "Tisch",          "color": "#44403c"},
    "desk":        {"de": "Schreibtisch",   "color": "#3f3f46"},
    "bed":         {"de": "Bett",           "color": "#1e3a5f"},
    "cabinet":     {"de": "Schrank",        "color": "#374151"},
    "other":       {"de": "Sonstiges",      "color": "#374151"},
}


# ---------------------------------------------------------------------------
# Session-Verwaltung
# ---------------------------------------------------------------------------

def create_session(sensor_id: str, room_id: str) -> str:
    session_id = str(uuid.uuid4())[:8]
    _sessions[session_id] = {
        "id":         session_id,
        "sensor_id":  sensor_id,
        "room_id":    room_id,
        "corners":    {},
        "computed":   None,
        "furniture":  [],
        "doors":      [],
        "created_at": time.time(),
    }
    return session_id


def get_session(session_id: str) -> Optional[dict]:
    return _sessions.get(session_id)


def delete_session(session_id: str) -> None:
    _sessions.pop(session_id, None)


def cleanup_old_sessions(max_age_s: float = 3600.0) -> int:
    """Löscht Sessions die älter als max_age_s Sekunden sind. Gibt Anzahl zurück."""
    cutoff = time.time() - max_age_s
    old = [sid for sid, s in _sessions.items() if s["created_at"] < cutoff]
    for sid in old:
        del _sessions[sid]
    return len(old)


# ---------------------------------------------------------------------------
# Raumecken markieren + Raummaße berechnen
# ---------------------------------------------------------------------------

def mark_corner(session_id: str, label: str, x_mm: float, y_mm: float) -> None:
    if label not in CORNER_DISPLAY:
        raise ValueError(f"Unbekannte Ecke: '{label}'")
    _sessions[session_id]["corners"][label] = {
        "x_mm": round(float(x_mm), 1),
        "y_mm": round(float(y_mm), 1),
    }


def _room_rel(xs: float, ys: float, cos_t: float, sin_t: float) -> tuple:
    """Sensor-Koordinaten → Raum-relative Koordinaten (ohne Sensoroffset)."""
    return xs * cos_t + ys * sin_t, -xs * sin_t + ys * cos_t


def compute_room(session_id: str) -> dict:
    """
    Berechnet Raummaße und Sensorposition aus den vier markierten Ecken.

    Mathematisches Vorgehen:
      1. Rotation: Winkel des Vektors back_left → back_right im Sensorraum.
         Dieser Vektor zeigt in Raum-+x-Richtung → definiert rotation_deg.
      2. Alle vier Ecken in raumrelative Koordinaten transformieren.
      3. width_mm  = max_rx − min_rx (Ausdehnung in Raum-x)
      4. height_mm = mittlere ry der hinteren Ecken (Abstand Sensor – Rückwand)
      5. sensor_x_mm = −min_rx  (Sensor ist Ursprung; linke Wand bei min_rx)
      6. sensor_y_mm = 0        (Sensor sitzt an der y=0-Wand)
    """
    session = _sessions[session_id]
    corners = session["corners"]

    missing = [c for c in CORNER_SEQUENCE if c not in corners]
    if missing:
        raise ValueError(f"Noch nicht markiert: {', '.join(missing)}")

    bl = corners["back_left"]
    br = corners["back_right"]
    fl = corners["front_left"]
    fr = corners["front_right"]

    # --- Rotation ---
    dx = br["x_mm"] - bl["x_mm"]
    dy = br["y_mm"] - bl["y_mm"]
    rotation_deg = round(math.degrees(math.atan2(dy, dx)), 1)

    cos_t = math.cos(math.radians(rotation_deg))
    sin_t = math.sin(math.radians(rotation_deg))

    # --- Alle Ecken in Raum-relative Koordinaten ---
    bl_rx, bl_ry = _room_rel(bl["x_mm"], bl["y_mm"], cos_t, sin_t)
    br_rx, br_ry = _room_rel(br["x_mm"], br["y_mm"], cos_t, sin_t)
    fl_rx, fl_ry = _room_rel(fl["x_mm"], fl["y_mm"], cos_t, sin_t)
    fr_rx, fr_ry = _room_rel(fr["x_mm"], fr["y_mm"], cos_t, sin_t)

    all_rx = [bl_rx, br_rx, fl_rx, fr_rx]
    min_rx = min(all_rx)
    max_rx = max(all_rx)

    width_mm    = max_rx - min_rx
    height_mm   = (bl_ry + br_ry) / 2.0   # Rückwand-Abstand
    sensor_x_mm = -min_rx
    sensor_y_mm = 0

    result = {
        "width_mm":     round(width_mm),
        "height_mm":    round(height_mm),
        "sensor_x_mm":  round(sensor_x_mm),
        "sensor_y_mm":  sensor_y_mm,
        "rotation_deg": rotation_deg,
    }
    session["computed"] = result
    return result


# ---------------------------------------------------------------------------
# Möbel markieren + Position berechnen
# ---------------------------------------------------------------------------

def add_furniture(session_id: str, name: str, ftype: str, is_zone: bool) -> str:
    session = _sessions[session_id]
    fid = str(uuid.uuid4())[:8]
    session["furniture"].append({
        "id":       fid,
        "name":     name,
        "type":     ftype if ftype in FURNITURE_TYPES else "other",
        "is_zone":  is_zone,
        "corners":  {},
        "computed": None,
    })
    return fid


def get_furniture(session_id: str, fid: str) -> Optional[dict]:
    session = _sessions.get(session_id)
    if not session:
        return None
    return next((f for f in session["furniture"] if f["id"] == fid), None)


def mark_furniture_corner(session_id: str, fid: str, corner: str,
                          x_mm: float, y_mm: float) -> None:
    item = get_furniture(session_id, fid)
    if not item:
        raise ValueError(f"Möbelstück '{fid}' nicht gefunden")
    if corner not in ("a", "b"):
        raise ValueError("corner muss 'a' oder 'b' sein")
    item["corners"][corner] = {"x_mm": round(float(x_mm), 1), "y_mm": round(float(y_mm), 1)}


# ---------------------------------------------------------------------------
# Türen markieren + Position berechnen
# ---------------------------------------------------------------------------

def add_door(session_id: str, name: str, connects_to: str) -> str:
    session = _sessions[session_id]
    did = str(uuid.uuid4())[:8]
    session.setdefault("doors", []).append({
        "id":          did,
        "name":        name,
        "connects_to": connects_to,
        "points":      {},   # "a" und "b" – je ein Sensor-Koordinaten-Paar
        "computed":    None,
    })
    return did


def get_door(session_id: str, did: str) -> Optional[dict]:
    session = _sessions.get(session_id)
    if not session:
        return None
    return next((d for d in session.get("doors", []) if d["id"] == did), None)


def mark_door_point(session_id: str, did: str, point: str,
                    x_mm: float, y_mm: float) -> None:
    door = get_door(session_id, did)
    if not door:
        raise ValueError(f"Tür '{did}' nicht gefunden")
    if point not in ("a", "b"):
        raise ValueError("point muss 'a' oder 'b' sein")
    door["points"][point] = {"x_mm": round(float(x_mm), 1), "y_mm": round(float(y_mm), 1)}


def compute_door(session_id: str, did: str) -> dict:
    """
    Berechnet Wandzugehörigkeit, Position und Breite einer Tür aus zwei
    markierten Punkten an den Türkanten.

    Rückgabe:
        {
          "wall":        "top" | "bottom" | "left" | "right",
          "position_mm": float,   # Abstand vom Wandanfang zur Türkante
          "width_mm":    float,   # Türbreite
        }

    Wandkonvention (Raumkoordinaten):
        top    → y = 0          (Sensor-Wand)
        bottom → y = height_mm
        left   → x = 0
        right  → x = width_mm
        position_mm für top/bottom: Abstand von x=0
        position_mm für left/right: Abstand von y=0
    """
    session = _sessions[session_id]
    door = get_door(session_id, did)
    if not door:
        raise ValueError(f"Tür '{did}' nicht gefunden")
    if "a" not in door["points"] or "b" not in door["points"]:
        raise ValueError("Beide Punkte (a und b) müssen markiert sein")

    comp = session.get("computed") or {}
    rotation_deg = comp.get("rotation_deg", 0)
    sx = comp.get("sensor_x_mm", 0)
    sy = comp.get("sensor_y_mm", 0)
    width_mm  = comp.get("width_mm",  0)
    height_mm = comp.get("height_mm", 0)

    cos_t = math.cos(math.radians(rotation_deg))
    sin_t = math.sin(math.radians(rotation_deg))

    def to_room(p):
        rx, ry = _room_rel(p["x_mm"], p["y_mm"], cos_t, sin_t)
        return sx + rx, sy + ry

    ax, ay = to_room(door["points"]["a"])
    bx, by = to_room(door["points"]["b"])
    cx, cy = (ax + bx) / 2, (ay + by) / 2  # Mittelpunkt der Tür

    # Nächste Wand anhand Mittelpunkt bestimmen
    dist_top    = cy
    dist_bottom = height_mm - cy
    dist_left   = cx
    dist_right  = width_mm  - cx

    nearest = min(
        ("top",    dist_top),
        ("bottom", dist_bottom),
        ("left",   dist_left),
        ("right",  dist_right),
        key=lambda t: t[1],
    )
    wall = nearest[0]

    if wall in ("top", "bottom"):
        pos = round(min(ax, bx))
        w   = round(abs(bx - ax))
    else:  # left, right
        pos = round(min(ay, by))
        w   = round(abs(by - ay))

    result = {"wall": wall, "position_mm": pos, "width_mm": w}
    door["computed"] = result
    return result


def compute_furniture_pos(session_id: str, fid: str) -> dict:
    """
    Berechnet Position und Abmessung eines Möbelstücks aus zwei diagonal
    gegenüberliegenden Ecken (a und b) in Sensor-Koordinaten.
    """
    session = _sessions[session_id]
    item = get_furniture(session_id, fid)
    if not item:
        raise ValueError(f"Möbelstück '{fid}' nicht gefunden")
    if "a" not in item["corners"] or "b" not in item["corners"]:
        raise ValueError("Beide Ecken (a und b) müssen markiert sein")

    comp = session.get("computed") or {}
    rotation_deg = comp.get("rotation_deg", 0)
    sx = comp.get("sensor_x_mm", 0)
    sy = comp.get("sensor_y_mm", 0)

    cos_t = math.cos(math.radians(rotation_deg))
    sin_t = math.sin(math.radians(rotation_deg))

    def to_room(p):
        rx, ry = _room_rel(p["x_mm"], p["y_mm"], cos_t, sin_t)
        return sx + rx, sy + ry

    ax, ay = to_room(item["corners"]["a"])
    bx, by = to_room(item["corners"]["b"])

    result = {
        "x_mm":      round(min(ax, bx)),
        "y_mm":      round(min(ay, by)),
        "width_mm":  round(abs(bx - ax)),
        "height_mm": round(abs(by - ay)),
    }
    item["computed"] = result
    return result
