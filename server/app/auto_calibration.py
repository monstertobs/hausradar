"""
Auto-Kalibrierung für HausRadar-Sensoren.

Sammelt Roh-Sensor-Koordinaten (x_mm, y_mm direkt vom LD2450) in einem
Ringpuffer und schätzt dann per Grid-Search die optimalen Parameter:

  rotation_deg – welche Rotation bringt die meisten Punkte in den Raum?
  x_mm         – lateraler Sensor-Offset in Raumkoordinaten

Voraussetzung: Raumabmessungen (width_mm, height_mm) müssen bekannt sein.
Sensor-y bleibt auf 0 (Sensor an y=0-Wand, Standard-Montage).

Genauigkeit steigt mit der Anzahl gesammelter Messungen (Ziel: 500+).
"""

import math
import threading
from typing import Dict, List, Optional, Tuple

MIN_SAMPLES        = 200    # Mindest-Messungen für ersten Vorschlag
GOOD_SAMPLES       = 500    # Ab hier gilt der Vorschlag als zuverlässig
MAX_SAMPLES        = 3000   # Ringpuffer-Größe je Sensor
CANDIDATE_ROTATIONS = [0, 90, 180, 270]

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
