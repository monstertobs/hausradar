"""
Automatische Möbel-Erkennung aus Verweilmustern für HausRadar.

Algorithmus:
  1. Dwell-Tracking: Jeder Track bekommt einen DwellState. Bleibt die Person
     innerhalb von DWELL_RADIUS_MM, zählt die Zeit als Verweil-Zeit.
     Sobald sie sich bewegt oder verschwindet → Verweil-Event aufzeichnen.

  2. Clustering: Verweil-Events werden räumlich geclustert (einfaches
     Single-Linkage nach CLUSTER_RADIUS_MM). Jede Cluster-Gruppe = Dwell-Zone.

  3. Klassifikation: Jede Zone bekommt eine Wahrscheinlichkeitsverteilung
     über Möbeltypen anhand von avg_dwell_s, visit_count und radius_mm.

  4. Persistenz: Dwell-Zonen werden in config/dwell_zones.json gespeichert
     und beim Start geladen.

Möbeltyp-Heuristik:
  sofa/couch  – lange Verweildauer (>5min), mäßige Besuchshäufigkeit
  chair       – mittlere Verweildauer (1–10min), kleiner Radius
  table       – viele kurze Besuche, größerer Radius (Person steht drum herum)
  bed         – sehr lange Verweildauer (>30min), wenige Besuche (Nacht)
  desk        – mittlere Verweildauer, häufige Besuche (Arbeit am Schreibtisch)
  other       – passt auf nichts davon
"""

import json
import math
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import uuid

# ──────────────────────────────────────────────────────────────────────────────
# Konfiguration
# ──────────────────────────────────────────────────────────────────────────────

DWELL_RADIUS_MM  = 400   # Person gilt als "sitzend/stehend" wenn Bewegung < 400mm
MIN_DWELL_S      = 8.0   # Mindest-Verweildauer für ein Event (Sekunden)
CLUSTER_RADIUS_MM = 600  # Zwei Events innerhalb 600mm → gleiche Zone
MAX_ZONES        = 200   # Maximale Zonen pro Raum
ZONE_DECAY_DAYS  = 90    # Zonen ohne Besuche > 90 Tage werden entfernt

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "dwell_zones.json"

_lock        = threading.Lock()
_zones:      List[dict] = []    # persistierte Dwell-Zonen
_dwell_state: Dict[str, Dict[int, dict]] = {}  # sensor_id → track_id → state


# ──────────────────────────────────────────────────────────────────────────────
# Persistenz
# ──────────────────────────────────────────────────────────────────────────────

def load() -> None:
    global _zones
    with _lock:
        if _CONFIG_PATH.exists():
            try:
                data = json.loads(_CONFIG_PATH.read_text())
                _zones = data if isinstance(data, list) else []
            except Exception:
                _zones = []
        else:
            _zones = []


def _save() -> None:
    try:
        _CONFIG_PATH.write_text(json.dumps(_zones, indent=2))
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Dwell-Tracking (aufgerufen aus mqtt_service pro Frame)
# ──────────────────────────────────────────────────────────────────────────────

def update_tracks(sensor_id: str, room_id: str,
                  real_tracks: List[dict], disappeared_ids: List[int]) -> None:
    """
    Verarbeitet einen neuen Frame.

    real_tracks:     Liste aktueller (nicht-Ghost) Tracks mit room_x_mm, room_y_mm, track_id
    disappeared_ids: track_ids die in diesem Frame verschwunden sind
    """
    now = time.time()

    with _lock:
        sensor_states = _dwell_state.setdefault(sensor_id, {})

        # Verschwundene Tracks abschließen
        for tid in disappeared_ids:
            state = sensor_states.pop(tid, None)
            if state:
                dur = now - state["ts"]
                if dur >= MIN_DWELL_S:
                    _record_event(room_id, state["x"], state["y"], dur, now)

        # Aktive Tracks aktualisieren
        for t in real_tracks:
            tid = t.get("track_id", t.get("id", 0))
            x, y = t.get("room_x_mm", 0), t.get("room_y_mm", 0)

            if tid not in sensor_states:
                sensor_states[tid] = {"x": x, "y": y, "ts": now}
                continue

            state = sensor_states[tid]
            dist  = math.hypot(x - state["x"], y - state["y"])

            if dist > DWELL_RADIUS_MM:
                # Bewegt – Event abschließen wenn lang genug
                dur = now - state["ts"]
                if dur >= MIN_DWELL_S:
                    _record_event(room_id, state["x"], state["y"], dur, now)
                # Neue Dwell-Position starten
                sensor_states[tid] = {"x": x, "y": y, "ts": now}


# ──────────────────────────────────────────────────────────────────────────────
# Event aufzeichnen + in Zone einpflegen
# ──────────────────────────────────────────────────────────────────────────────

def _record_event(room_id: str, x: float, y: float,
                  duration_s: float, ts: float) -> None:
    """Muss unter _lock aufgerufen werden."""
    room_zones = [z for z in _zones if z["room_id"] == room_id]

    # Nächste Zone innerhalb CLUSTER_RADIUS suchen
    nearest = None
    nearest_dist = float("inf")
    for zone in room_zones:
        d = math.hypot(zone["center_x"] - x, zone["center_y"] - y)
        if d < nearest_dist:
            nearest_dist = d
            nearest = zone

    if nearest and nearest_dist <= CLUSTER_RADIUS_MM:
        # In bestehende Zone einpflegen (gleitender Mittelwert des Zentrums)
        n = nearest["visit_count"]
        nearest["center_x"]     = (nearest["center_x"] * n + x) / (n + 1)
        nearest["center_y"]     = (nearest["center_y"] * n + y) / (n + 1)
        nearest["visit_count"] += 1
        nearest["total_dwell_s"] += duration_s
        nearest["max_dwell_s"]   = max(nearest["max_dwell_s"], duration_s)
        nearest["ts_last"]       = ts
        _update_radius(nearest, x, y)
        _classify(nearest)
    else:
        # Neue Zone anlegen
        if sum(1 for z in _zones if z["room_id"] == room_id) >= MAX_ZONES:
            return
        zone = {
            "id":           str(uuid.uuid4())[:8],
            "room_id":      room_id,
            "center_x":     x,
            "center_y":     y,
            "radius_mm":    200,
            "visit_count":  1,
            "total_dwell_s": duration_s,
            "max_dwell_s":  duration_s,
            "ts_last":      ts,
            "ts_created":   ts,
            # Punktwolke für Radius-Schätzung (letzte 50 Positionen)
            "_points":      [[x, y]],
            "probabilities": {},
            "suggested_type": "other",
            "confidence":   0.0,
        }
        _classify(zone)
        _zones.append(zone)

    _save()


def _update_radius(zone: dict, x: float, y: float) -> None:
    points = zone.setdefault("_points", [])
    points.append([x, y])
    if len(points) > 50:
        del points[0]
    if len(points) >= 3:
        cx, cy = zone["center_x"], zone["center_y"]
        dists  = [math.hypot(p[0] - cx, p[1] - cy) for p in points]
        dists.sort()
        zone["radius_mm"] = round(dists[int(len(dists) * 0.85)])  # 85. Perzentile


# ──────────────────────────────────────────────────────────────────────────────
# Wahrscheinlichkeits-Klassifikation
# ──────────────────────────────────────────────────────────────────────────────

def _sig(x: float, scale: float = 1.0) -> float:
    """Logistische Funktion: glatter Übergang 0→1."""
    return 1.0 / (1.0 + math.exp(-x / max(scale, 1e-9)))


def _classify(zone: dict) -> None:
    n      = zone["visit_count"]
    total  = zone["total_dwell_s"]
    avg    = total / max(n, 1)
    mx     = zone["max_dwell_s"]
    r      = zone.get("radius_mm", 200)

    scores: Dict[str, float] = {}

    # Sofa / Couch – lange Verweildauer, entspannte Nutzung
    scores["sofa"] = (
        _sig(avg - 300,  scale=200) *    # avg > 5min
        _sig(mx  - 600,  scale=300) *    # max > 10min (wurde wirklich genutzt)
        _sig(n   - 3,    scale=5)  *     # mehrfach besucht
        _sig(500 - r,    scale=150)      # nicht zu großer Radius
    )

    # Stuhl / Sessel – mittlere Verweildauer
    scores["chair"] = (
        _sig(avg - 30,   scale=30) *     # avg > 30s
        _sig(400 - avg,  scale=200) *    # avg < 6-7min
        _sig(n   - 2,    scale=4)  *
        _sig(350 - r,    scale=100)      # kleiner Radius
    )

    # Esstisch – viele eher kurze Besuche, Mahlzeiten
    scores["table"] = (
        _sig(n   - 10,   scale=15) *     # viele Besuche
        _sig(avg - 20,   scale=20) *     # avg > 20s (nicht nur Durchgang)
        _sig(300 - avg,  scale=150) *    # avg < 5min
        _sig(r   - 200,  scale=150)      # etwas größerer Radius
    )

    # Schreibtisch – regelmäßige, mittel-lange Verweildauer
    scores["desk"] = (
        _sig(avg - 120,  scale=120) *    # avg > 2min
        _sig(n   - 5,    scale=10)  *    # regelmäßig
        _sig(400 - r,    scale=120)      # nicht riesig
    )

    # Bett – sehr lange Verweildauer, wenige Besuche (Nacht)
    scores["bed"] = (
        _sig(avg - 1800, scale=600) *    # avg > 30min
        _sig(mx  - 3600, scale=1200) *   # max > 1h
        _sig(20  - n,    scale=15)       # wenige Besuche (nicht oft gemessen)
    )

    # Normalisieren
    total_score = sum(scores.values()) or 1e-9
    probs = {k: round(v / total_score, 3) for k, v in scores.items()}
    best  = max(probs, key=probs.__getitem__)

    zone["probabilities"]  = probs
    zone["suggested_type"] = best
    zone["confidence"]     = round(probs[best], 3)


# ──────────────────────────────────────────────────────────────────────────────
# Öffentliche API
# ──────────────────────────────────────────────────────────────────────────────

def get_zones(room_id: Optional[str] = None) -> List[dict]:
    """Gibt Zonen zurück (ohne interne _points-Liste)."""
    with _lock:
        result = []
        for z in _zones:
            if room_id and z["room_id"] != room_id:
                continue
            public = {k: v for k, v in z.items() if not k.startswith("_")}
            public["avg_dwell_s"] = round(
                z["total_dwell_s"] / max(z["visit_count"], 1), 1
            )
            result.append(public)
        return result


def delete_zone(zone_id: str) -> bool:
    with _lock:
        before = len(_zones)
        _zones[:] = [z for z in _zones if z["id"] != zone_id]
        if len(_zones) < before:
            _save()
            return True
        return False


def clear_room(room_id: str) -> int:
    with _lock:
        before = len(_zones)
        _zones[:] = [z for z in _zones if z["room_id"] != room_id]
        removed = before - len(_zones)
        if removed:
            _save()
        return removed


def prune_old_zones() -> int:
    """Entfernt Zonen die länger als ZONE_DECAY_DAYS nicht besucht wurden."""
    cutoff = time.time() - ZONE_DECAY_DAYS * 86400
    with _lock:
        before = len(_zones)
        _zones[:] = [z for z in _zones if z.get("ts_last", 0) >= cutoff]
        removed = before - len(_zones)
        if removed:
            _save()
        return removed
