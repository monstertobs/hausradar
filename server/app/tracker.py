"""
Personen-Tracker für HausRadar.

Ordnet eingehende Sensor-Messungen stabilen Personen-Tracks zu, damit

  1. Die IDs beim LD2450 (Slot 0/1/2) zwischen Frames nicht springen.
  2. Kurze Aussetzer (<= MAX_MISS_FRAMES) überbrückt werden (Ghost-Frame),
     sodass Punkte auf der Karte nicht für 1-2 Frames verschwinden.
  3. Jeder Track eine stabile Farb-ID (0=blau 1=orange 2=grün) behält.

Algorithmus: Greedy Nearest-Neighbour in Raum-Koordinaten.
Thread-sicher durch internen Lock je Tracker-Instanz.
"""

import math
import threading

# ──────────────────────────────────────────────────────────────────────────────
# Konfiguration
# ──────────────────────────────────────────────────────────────────────────────

MAX_ASSIGN_DIST_MM = 800   # mm – max. Distanz für eine Zuordnung
MAX_MISS_FRAMES    = 4     # Frames ohne Messung → dann Track löschen
_COLOR_COUNT       = 3     # Anzahl verfügbarer Farben (Indizes 0, 1, 2)


# ──────────────────────────────────────────────────────────────────────────────
# Internes Track-Objekt
# ──────────────────────────────────────────────────────────────────────────────

class _Track:
    __slots__ = ("track_id", "color_idx", "x_room", "y_room", "last_data",
                 "miss", "age")

    def __init__(self, track_id: int, color_idx: int, data: dict) -> None:
        self.track_id  = track_id
        self.color_idx = color_idx
        self.x_room    = data["room_x_mm"]
        self.y_room    = data["room_y_mm"]
        self.last_data = data   # vollständige letzte Messung
        self.miss      = 0
        self.age       = 1


# ──────────────────────────────────────────────────────────────────────────────
# PersonTracker
# ──────────────────────────────────────────────────────────────────────────────

class PersonTracker:
    """Thread-sicherer Tracker für einen einzelnen Sensor."""

    def __init__(self) -> None:
        self._tracks:       list        = []
        self._next_id:      int         = 0
        self._free_colors:  list        = list(range(_COLOR_COUNT))
        self._lock = threading.Lock()

    def update(self, enriched: list) -> list:
        """
        Eingabe:  enriched – Liste von Ziel-Dicts aus coordinate_transform,
                  jedes mit den Feldern room_x_mm, room_y_mm, inside_room, …
        Ausgabe:  Liste mit denselben Dicts + track_id, color_idx, ghost.
                  Ghost-Einträge (kurze Aussetzer) haben ghost=True und
                  tragen die letzte bekannte Position.
        """
        with self._lock:
            return self._run(enriched)

    def _run(self, enriched: list) -> list:
        # Nur Messungen innerhalb des Raums zählen für die Zuordnung
        meas = [t for t in enriched if t.get("inside_room", True)]

        n_t = len(self._tracks)
        n_m = len(meas)

        # ── Distanzpaare berechnen und sortieren ──────────────────────────────
        pairs: list = []
        for ti in range(n_t):
            tr = self._tracks[ti]
            for mi in range(n_m):
                m = meas[mi]
                d = math.hypot(tr.x_room - m["room_x_mm"],
                               tr.y_room - m["room_y_mm"])
                pairs.append((d, ti, mi))
        pairs.sort()

        # ── Greedy Nearest-Neighbour Assignment ───────────────────────────────
        used_t: set = set()
        used_m: set = set()
        assignment: dict = {}        # ti → mi

        for d, ti, mi in pairs:
            if d > MAX_ASSIGN_DIST_MM:
                break
            if ti in used_t or mi in used_m:
                continue
            assignment[ti] = mi
            used_t.add(ti)
            used_m.add(mi)

        # ── Bestehende Tracks aktualisieren ───────────────────────────────────
        for ti, track in enumerate(self._tracks):
            if ti in assignment:
                m = meas[assignment[ti]]
                track.x_room    = m["room_x_mm"]
                track.y_room    = m["room_y_mm"]
                track.last_data = m
                track.miss      = 0
                track.age      += 1
            else:
                track.miss += 1

        # ── Tote Tracks entfernen, Farben freigeben ───────────────────────────
        surviving = []
        for track in self._tracks:
            if track.miss <= MAX_MISS_FRAMES:
                surviving.append(track)
            else:
                self._free_colors.append(track.color_idx)
                self._free_colors.sort()
        self._tracks = surviving

        # ── Neue Tracks für ungematchte Messungen ─────────────────────────────
        for mi, m in enumerate(meas):
            if mi not in used_m:
                c = (self._free_colors.pop(0)
                     if self._free_colors
                     else self._next_id % _COLOR_COUNT)
                self._tracks.append(_Track(self._next_id, c, m))
                self._next_id += 1

        # ── Ausgabe aufbauen ─────────────────────────────────────────────────
        result = []
        for track in self._tracks:
            entry = dict(track.last_data)
            entry["track_id"]  = track.track_id
            entry["color_idx"] = track.color_idx
            entry["ghost"]     = track.miss > 0
            result.append(entry)

        return result


# ──────────────────────────────────────────────────────────────────────────────
# Globale Tracker-Registry (eine Instanz pro Sensor-ID)
# ──────────────────────────────────────────────────────────────────────────────

_registry:      dict = {}
_registry_lock = threading.Lock()


def get_tracker(sensor_id: str) -> PersonTracker:
    """Gibt den Tracker für sensor_id zurück, legt ihn bei Bedarf an."""
    with _registry_lock:
        if sensor_id not in _registry:
            _registry[sensor_id] = PersonTracker()
        return _registry[sensor_id]


def clear_all() -> None:
    """Leert die Registry – nur für Tests."""
    with _registry_lock:
        _registry.clear()
