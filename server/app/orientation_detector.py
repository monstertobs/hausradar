"""
Sensor-Montageerkennung aus Bewegungsmustern für HausRadar.

Analysiert die Streuung der rohen LD2450-Koordinaten (x_mm, y_mm):
  y_mm = Tiefenabstand vom Sensor (immer positiv)
  x_mm = laterale Position (links/rechts)

Klassifikation:
  Wandmontage (normal): Person läuft quer + in die Tiefe → std_y groß
  Deckenmontage:        Person immer ~500mm unter Sensor → std_y sehr klein,
                        std_x groß (kreisförmige Bewegung in der Ebene)
  Gedreht (90°):        std_x << std_y (Sensor auf der Seite montiert)
  Unbekannt:            Noch nicht genug Daten (< MIN_SAMPLES)

Verwendet den Welford-Online-Algorithmus für inkrementelle Varianzberechnung.
"""

import math
import threading
from typing import Dict, Optional

MIN_SAMPLES = 150   # Mindest-Messungen vor erster Schätzung

_lock    = threading.Lock()
_sensors: Dict[str, "_WelfordState"] = {}


# ──────────────────────────────────────────────────────────────────────────────
# Welford-State pro Sensor
# ──────────────────────────────────────────────────────────────────────────────

class _WelfordState:
    __slots__ = ("n", "mean_x", "M2_x", "mean_y", "M2_y")

    def __init__(self) -> None:
        self.n      = 0
        self.mean_x = 0.0
        self.M2_x   = 0.0
        self.mean_y = 0.0
        self.M2_y   = 0.0

    def update(self, x: float, y: float) -> None:
        self.n += 1
        dx = x - self.mean_x
        self.mean_x += dx / self.n
        self.M2_x   += dx * (x - self.mean_x)

        dy = y - self.mean_y
        self.mean_y += dy / self.n
        self.M2_y   += dy * (y - self.mean_y)

    def std_x(self) -> float:
        return math.sqrt(self.M2_x / (self.n - 1)) if self.n > 1 else 0.0

    def std_y(self) -> float:
        return math.sqrt(self.M2_y / (self.n - 1)) if self.n > 1 else 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Öffentliche API
# ──────────────────────────────────────────────────────────────────────────────

def update(sensor_id: str, x_mm: float, y_mm: float) -> None:
    """Fügt eine Rohkoordinaten-Messung zur Statistik hinzu."""
    with _lock:
        if sensor_id not in _sensors:
            _sensors[sensor_id] = _WelfordState()
        _sensors[sensor_id].update(x_mm, y_mm)


def get_orientation(sensor_id: str) -> Optional[dict]:
    """
    Gibt eine Montage-Schätzung zurück, sobald genug Daten vorliegen.
    Rückgabe: dict mit mount_type, confidence, std_x_mm, std_y_mm, sample_count
    Oder None wenn < MIN_SAMPLES vorhanden.

    mount_type:
      "wall"          – Normalmontage (Sensor an Wand, zeigt in den Raum)
      "ceiling"       – Deckenmontage (y_mm variiert kaum)
      "wall_rotated"  – Sensor 90° gedreht (x und y vertauscht)
      "unknown"       – Nicht eindeutig klassifizierbar
    """
    with _lock:
        state = _sensors.get(sensor_id)

    if state is None or state.n < MIN_SAMPLES:
        return None

    sx = state.std_x()
    sy = max(state.std_y(), 1.0)   # Division durch Null vermeiden
    n  = state.n

    ratio = sx / sy   # > 1 → x breiter als y, < 1 → y tiefer als x

    # Deckenmontage: y variiert kaum, weil Person immer gleichweit unter Sensor
    if sy < 250 or ratio > 3.0:
        mount_type = "ceiling"
        # Konfidenz steigt mit kleinem sy und vielen Samples
        conf = min(1.0, (max(250 - sy, 0) / 200 + n / 500))

    # Gedreht: x variiert viel weniger als y (Sensor 90° auf der Seite)
    elif ratio < 0.35:
        mount_type = "wall_rotated"
        conf = min(1.0, (0.35 - ratio) / 0.25 + n / 500)

    # Wandmontage normal: beide Achsen haben nennenswerte Streuung, y ≥ x
    elif sy > 400 and 0.35 <= ratio <= 3.0:
        mount_type = "wall"
        # Je näher ratio an 0.6–1.5, desto sicherer
        conf = min(1.0, min(sy / 800, 1.0) * min(n / 300, 1.0))

    else:
        mount_type = "unknown"
        conf = 0.3

    return {
        "mount_type":   mount_type,
        "confidence":   round(min(1.0, conf), 2),
        "sample_count": n,
        "std_x_mm":     round(sx, 1),
        "std_y_mm":     round(sy, 1),
        "ratio_x_y":    round(ratio, 2),
        "mean_y_mm":    round(state.mean_y, 1),
    }


def get_all_orientations() -> dict:
    """Gibt Orientierungsschätzungen für alle bekannten Sensoren zurück."""
    with _lock:
        ids = list(_sensors.keys())
    return {sid: o for sid in ids if (o := get_orientation(sid)) is not None}


def reset(sensor_id: str) -> None:
    """Setzt Statistik für einen Sensor zurück."""
    with _lock:
        _sensors.pop(sensor_id, None)
