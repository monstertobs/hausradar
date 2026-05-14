"""
Auto-Kalibrierung für HausRadar-Sensoren.

Sammelt Roh-Sensor-Koordinaten (x_mm, y_mm direkt vom LD2450) in einem
Ringpuffer und schätzt dann per Grid-Search die optimalen Parameter:

  rotation_deg – welche Rotation bringt die meisten Punkte in den Raum?
  x_mm         – lateraler Sensor-Offset in Raumkoordinaten

Zusätzlich (M23): Raumabmessungen aus Bewegungsprofil schätzen.
  suggest_room_size() – kein manuelles Eingeben mehr nötig.

  Methode:
    dim_depth   = P97(y_mm)  + WALL_CLEARANCE_MM
    dim_lateral = P97(x_mm) - P3(x_mm) + 2 × WALL_CLEARANCE_MM

  Die Achsenzuordnung (welche Dim = Breite, welche = Tiefe) folgt aus
  der Rotationsschätzung (0°/180° → depth=Höhe; 90°/270° → depth=Breite).
"""

import math
import threading
from typing import Dict, List, Optional, Tuple

MIN_SAMPLES         = 200    # Mindest-Messungen für ersten Vorschlag
GOOD_SAMPLES        = 500    # Ab hier gilt der Vorschlag als zuverlässig
MAX_SAMPLES         = 3000   # Ringpuffer-Größe je Sensor
CANDIDATE_ROTATIONS = [0, 90, 180, 270]
WALL_CLEARANCE_MM   = 400    # Typischer Mindestabstand Person–Wand

_lock    = threading.Lock()
_buffers: Dict[str, List[Tuple[float, float]]] = {}   # sensor_id → [(xs, ys)]


# ──────────────────────────────────────────────────────────────────────────────
# Datenerfassung
# ──────────────────────────────────────────────────────────────────────────────

def update(sensor_id: str, x_mm: float, y_mm: float) -> None:
    """Fügt eine Rohkoordinaten-Messung in den Ringpuffer ein."""
    with _lock:
        buf = _buffers.setdefault(sensor_id, [])
        buf.append((x_mm, y_mm))
        if len(buf) > MAX_SAMPLES:
            del buf[0]


def get_sample_count(sensor_id: str) -> int:
    with _lock:
        return len(_buffers.get(sensor_id, []))


def reset(sensor_id: str) -> None:
    """Löscht den Datenpuffer für einen Sensor."""
    with _lock:
        _buffers.pop(sensor_id, None)


def get_all_counts() -> Dict[str, int]:
    with _lock:
        return {sid: len(buf) for sid, buf in _buffers.items()}


# ──────────────────────────────────────────────────────────────────────────────
# Schätzung
# ──────────────────────────────────────────────────────────────────────────────

def suggest(sensor_id: str, room: dict) -> Optional[dict]:
    """
    Schätzt optimale Kalibrierungsparameter für einen Sensor.

    Algorithmus:
      Für jeden Kandidaten-Winkel (0/90/180/270°):
        1. Schätze sensor_x_mm so, dass der Median der transformierten
           x-Koordinaten in die Raummitte fällt.
        2. Zähle wie viele Punkte damit in die Raumgrenzen fallen.
      Bester Winkel = höchster "inside_ratio".

    Rückgabe-Dict:
      rotation_deg  – empfohlener Winkel (int)
      sensor_x_mm   – empfohlener x-Offset (int, Raumkoordinaten)
      confidence    – 0–1 (wie sicher ist der Vorschlag)
      inside_ratio  – Anteil der Punkte im Raum beim besten Kandidaten
      sample_count  – Anzahl verwendeter Messungen
      quality       – "low" | "medium" | "high"
      candidates    – Liste aller 4 Kandidaten mit scores
    """
    with _lock:
        buf = list(_buffers.get(sensor_id, []))

    n = len(buf)
    if n < MIN_SAMPLES:
        return None

    w = room.get("width_mm", 0)
    h = room.get("height_mm", 0)
    if w <= 0 or h <= 0:
        return None

    best_rot   = 0
    best_score = -1.0
    best_sx    = w / 2.0
    candidates = []

    for rot_deg in CANDIDATE_ROTATIONS:
        cos_a = math.cos(math.radians(rot_deg))
        sin_a = math.sin(math.radians(rot_deg))

        # Transformierte x-Werte ohne Offset
        xs_raw = sorted(xs * cos_a + ys * sin_a for xs, ys in buf)
        median_x = xs_raw[n // 2]

        # Sensor-x so wählen dass Median in Raummitte liegt
        sx_est = w / 2.0 - median_x

        # Punkte im Raum zählen (sensor_y = 0)
        inside = sum(
            1 for xs, ys in buf
            if 0 <= sx_est + xs * cos_a + ys * sin_a <= w
            and 0 <= -xs * sin_a + ys * cos_a <= h
        )
        ratio = inside / n

        candidates.append({
            "rotation_deg": rot_deg,
            "sensor_x_mm":  round(sx_est),
            "inside_ratio": round(ratio, 3),
        })

        if ratio > best_score:
            best_score = ratio
            best_rot   = rot_deg
            best_sx    = sx_est

    # Konfidenz aus Abstand zum Zweitbesten + Datenmenge
    scores    = sorted((c["inside_ratio"] for c in candidates), reverse=True)
    margin    = scores[0] - scores[1] if len(scores) > 1 else scores[0]
    n_factor  = min(1.0, n / GOOD_SAMPLES)
    confidence = round(min(1.0, margin * 4.0 * n_factor + n_factor * 0.2), 2)

    quality = "high" if n >= GOOD_SAMPLES and confidence >= 0.6 else \
              "medium" if n >= MIN_SAMPLES and confidence >= 0.3 else "low"

    return {
        "rotation_deg": best_rot,
        "sensor_x_mm":  round(best_sx),
        "sensor_y_mm":  0,
        "confidence":   confidence,
        "inside_ratio": round(best_score, 3),
        "sample_count": n,
        "quality":      quality,
        "candidates":   candidates,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Raumgröße schätzen (M23)
# ──────────────────────────────────────────────────────────────────────────────

def _percentile(sorted_vals: list, p: float) -> float:
    """Lineares Interpolations-Perzentil einer sortierten Liste."""
    if not sorted_vals:
        return 0.0
    idx = (p / 100) * (len(sorted_vals) - 1)
    lo  = int(idx)
    hi  = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def suggest_room_size(sensor_id: str) -> Optional[dict]:
    """
    Schätzt Raumabmessungen aus dem Bewegungsprofil.

    Algorithmus:
      y_mm (Sensor-Tiefe, immer positiv) → P97 + WALL_CLEARANCE = Tiefendimension
      x_mm (lateral, zentriert ≈ 0)     → P97 - P3 + 2×WALL_CLEARANCE = Breitendimension

    Rotation (0°/180° vs 90°/270°) bestimmt, welche Dimension Breite und Höhe ist.
    Für die Rotationsschätzung ohne bekannte Raummaße wird ein großer Dummy-Raum
    verwendet; der Sensor-Symmetrie-Score dient als primärer Diskriminator.

    Rückgabe:
      width_mm, height_mm  – auf 100 mm gerundete Schätzwerte
      confidence           – 0–1
      quality              – "low" / "medium" / "high"
    """
    with _lock:
        buf = list(_buffers.get(sensor_id, []))

    n = len(buf)
    if n < MIN_SAMPLES:
        return None

    ys_sorted = sorted(p[1] for p in buf)
    xs_sorted = sorted(p[0] for p in buf)

    depth_raw = _percentile(ys_sorted, 97)
    lat_lo    = _percentile(xs_sorted,  3)
    lat_hi    = _percentile(xs_sorted, 97)

    dim_depth   = round((depth_raw + WALL_CLEARANCE_MM)          / 100) * 100
    dim_lateral = round((lat_hi - lat_lo + 2 * WALL_CLEARANCE_MM) / 100) * 100

    # Rotationsschätzung: Sensor-Symmetrie entscheidet über Achsenzuordnung.
    # Symmetrischer Sensor (Median x ≈ 0) → Rotation 0° oder 180°.
    # Für θ=0/180: Sensor an y=0-Wand → depth=Raumhöhe, lateral=Raumbreite.
    # Für θ=90/270: Sensor an x=0-Wand → depth=Raumbreite, lateral=Raumhöhe.
    #
    # Wir schätzen die wahrscheinlichere Rotation ohne Raummaße:
    # wenn die Tiefe (y_mm) deutlich größer als die Laterale ist,
    # sieht der Sensor eher einen "langen" Raum in seiner y-Richtung.
    # Der Rotations-Grid-Search mit einem Dummy-Raum wäre unzuverlässig
    # (alle Punkte fallen immer ins riesige Dummy-Rechteck).
    # Stattdessen: Symmetrie-Heuristik auf x_mm.
    #
    # x_mm ist bei korrekter Montage (Sensor mittig an Wand) lateral
    # und symmetrisch um 0. Ist der Sensor seitlich montiert (90°/270°),
    # entspricht x_mm dem Tiefenbereich → dann ist x_mm immer > 0 (oder immer < 0)
    # und stark asymmetrisch.
    median_x  = _percentile(xs_sorted, 50)
    x_span    = max(lat_hi - lat_lo, 1.0)
    # Normierter Offset des Medians innerhalb der Spanne
    sym_offset = abs(median_x - (lat_lo + lat_hi) / 2) / x_span

    # x_mm hat immer negative Werte → wahrscheinlich 90°/270° Montage
    # (bei 0°/180° kann x_mm negativ sein, aber Median liegt nahe 0)
    is_side_mount = (lat_lo >= 0 or lat_hi <= 0)  # einseitig positiv/negativ

    if is_side_mount:
        # 90° oder 270°: depth = Breite, lateral = Höhe
        width_mm  = int(dim_depth)
        height_mm = int(dim_lateral)
    else:
        # 0° oder 180°: depth = Höhe, lateral = Breite
        width_mm  = int(dim_lateral)
        height_mm = int(dim_depth)

    # Konfidenz: Datenmenge + laterale Symmetrie
    n_factor   = min(1.0, n / GOOD_SAMPLES)
    sym_score  = max(0.0, 1.0 - sym_offset * 2)
    confidence = round(min(1.0, n_factor * 0.7 + sym_score * 0.3), 2)

    quality = ("high"   if n >= GOOD_SAMPLES and confidence >= 0.60 else
               "medium" if n >= MIN_SAMPLES  and confidence >= 0.35 else
               "low")

    return {
        "width_mm":    width_mm,
        "height_mm":   height_mm,
        "confidence":  confidence,
        "quality":     quality,
        "sample_count": n,
    }
