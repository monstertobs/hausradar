"""
Automatische Türerkennung aus Bewegungsmustern.

Wenn eine Person einen Raum verlässt (Track verschwindet nahe einer Wand),
wird ein Exit-Event gespeichert. Häufen sich Events an derselben Wandposition,
entsteht ein Tür-Kandidat.

Verbindungserkennung:
  Wenn kurz nach einem Exit aus Raum A ein neuer Track in Raum B erscheint,
  werden die Räume als verbunden markiert.
  Erscheint niemand in einem anderen Raum → Außentür / Terrasse.
"""

import time
import threading
from typing import Dict, List, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────────────
# Konfiguration
# ──────────────────────────────────────────────────────────────────────────────

WALL_THRESHOLD_MM = 500   # Max. Abstand zur Wand damit ein Exit zählt
MIN_EXITS         = 4     # Mindest-Exits für einen Tür-Kandidaten
CLUSTER_DIST_MM   = 700   # Max. Wandabstand für denselben Cluster
CROSS_ROOM_SEC    = 8.0   # Zeitfenster für Raum-zu-Raum-Verbindung
MIN_CONNECTIONS   = 2     # Mindest-Korrelationen für "leads_to = Raum"
MAX_EVENTS        = 2000  # Maximale gespeicherte Exit-Events

# ──────────────────────────────────────────────────────────────────────────────
# Modulzustand (thread-sicher via Lock)
# ──────────────────────────────────────────────────────────────────────────────

_lock           = threading.Lock()
_exit_events:   List[dict] = []   # {room_id, wall, wall_pos_mm, x_mm, y_mm, ts}
_entry_events:  List[dict] = []   # {room_id, x_mm, y_mm, ts}


# ──────────────────────────────────────────────────────────────────────────────
# Öffentliche API
# ──────────────────────────────────────────────────────────────────────────────

def record_exit(room_id: str, x_mm: float, y_mm: float,
                room_width: float, room_height: float) -> None:
    """Speichert ein Exit-Event wenn die letzte Position nahe einer Wand liegt."""
    wall, wall_pos = _detect_wall(x_mm, y_mm, room_width, room_height)
    if wall is None:
        return

    with _lock:
        _exit_events.append({
            "room_id":    room_id,
            "wall":       wall,
            "wall_pos_mm": wall_pos,
            "x_mm":       x_mm,
            "y_mm":       y_mm,
            "ts":         time.time(),
        })
        if len(_exit_events) > MAX_EVENTS:
            del _exit_events[0]


def record_entry(room_id: str, x_mm: float, y_mm: float) -> None:
    """Speichert einen neuen Track-Eintritt (neuer Mensch erscheint im Raum)."""
    now = time.time()
    with _lock:
        _entry_events.append({"room_id": room_id, "x_mm": x_mm, "y_mm": y_mm, "ts": now})
        # Nur letzte 60 Sekunden behalten
        cutoff = now - 60
        while _entry_events and _entry_events[0]["ts"] < cutoff:
            del _entry_events[0]


def get_suggestions(rooms: list) -> list:
    """Berechnet Tür-Kandidaten aus allen gespeicherten Exit-Events."""
    room_map = {r["id"]: r for r in rooms}

    with _lock:
        events  = list(_exit_events)
        entries = list(_entry_events)

    # Gruppieren nach (room_id, wall)
    groups: Dict[Tuple[str, str], List[dict]] = {}
    for ev in events:
        key = (ev["room_id"], ev["wall"])
        groups.setdefault(key, []).append(ev)

    suggestions = []
    for (room_id, wall), wall_events in groups.items():
        room = room_map.get(room_id)
        if not room:
            continue

        for cluster in _cluster_events(wall_events, CLUSTER_DIST_MM):
            if len(cluster) < MIN_EXITS:
                continue

            avg_pos    = sum(e["wall_pos_mm"] for e in cluster) / len(cluster)
            positions  = sorted(e["wall_pos_mm"] for e in cluster)
            spread     = positions[-1] - positions[0] if len(positions) > 1 else 900
            width_est  = max(700, min(1800, spread + 400))
            confidence = min(1.0, round(len(cluster) / 10, 2))
            leads_to   = _find_connection(room_id, cluster, entries, room_map)

            suggestions.append({
                "room_id":     room_id,
                "room_name":   room.get("name", room_id),
                "wall":        wall,
                "position_mm": round(avg_pos),
                "width_mm":    round(width_est),
                "exit_count":  len(cluster),
                "confidence":  confidence,
                "leads_to":    leads_to,        # room_id | "outside" | None
                "ts_last":     max(e["ts"] for e in cluster),
            })

    suggestions.sort(key=lambda s: -s["confidence"])
    return suggestions


def get_stats() -> dict:
    with _lock:
        return {
            "exit_events":  len(_exit_events),
            "entry_events": len(_entry_events),
        }


def clear_events() -> None:
    """Löscht alle gesammelten Events (z.B. nach Bestätigung oder Fehler)."""
    with _lock:
        _exit_events.clear()
        _entry_events.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Interne Hilfsfunktionen
# ──────────────────────────────────────────────────────────────────────────────

def _detect_wall(x_mm: float, y_mm: float,
                 room_w: float, room_h: float) -> Tuple[Optional[str], float]:
    """
    Gibt (wall, wall_pos_mm) zurück wenn die Position nahe genug an einer Wand ist.
    wall_pos_mm = Position entlang der Wand (für Nord/Süd: x-Wert, für Ost/West: y-Wert).
    """
    # Wand-Namen müssen mit dem Floorplan-Renderer übereinstimmen:
    # top=y=0, bottom=y=height, left=x=0, right=x=width
    dist = {
        "top":    y_mm,
        "bottom": room_h - y_mm,
        "left":   x_mm,
        "right":  room_w - x_mm,
    }
    pos = {
        "top": x_mm, "bottom": x_mm,
        "left": y_mm, "right":  y_mm,
    }
    closest = min(dist, key=dist.__getitem__)
    if dist[closest] > WALL_THRESHOLD_MM:
        return None, 0.0
    return closest, pos[closest]


def _cluster_events(events: list, max_dist: float) -> List[List[dict]]:
    """1D-Clustering der Exit-Events nach wall_pos_mm (Single-Linkage)."""
    if not events:
        return []
    sorted_ev = sorted(events, key=lambda e: e["wall_pos_mm"])
    clusters: List[List[dict]] = [[sorted_ev[0]]]
    for ev in sorted_ev[1:]:
        if ev["wall_pos_mm"] - clusters[-1][-1]["wall_pos_mm"] <= max_dist:
            clusters[-1].append(ev)
        else:
            clusters.append([ev])
    return clusters


def _find_connection(room_id: str, cluster: list,
                     entries: list, room_map: dict) -> Optional[str]:
    """
    Sucht ob Exits aus diesem Cluster zeitlich mit Einträgen in anderen Räumen
    korrelieren.
    - Mehrere Korrelationen mit Raum X → "leads_to = X"
    - Keine Korrelationen → "outside"
    - Zu wenig Daten → None
    """
    room_hits: Dict[str, int] = {}
    total_checked = 0

    for ev in cluster:
        for entry in entries:
            if entry["room_id"] == room_id:
                continue
            dt = entry["ts"] - ev["ts"]
            if 0 < dt <= CROSS_ROOM_SEC:
                total_checked += 1
                r = entry["room_id"]
                room_hits[r] = room_hits.get(r, 0) + 1

    if not room_hits:
        # Keine Raumeintritte nach diesem Exit → Außenbereich
        return "outside" if len(cluster) >= MIN_EXITS * 2 else None

    best_room  = max(room_hits, key=room_hits.__getitem__)
    best_count = room_hits[best_room]

    if best_count >= MIN_CONNECTIONS:
        return best_room   # Raum-ID des verbundenen Raums

    return None  # Noch zu wenig Daten
