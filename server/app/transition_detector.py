"""
Raum-zu-Raum-Transitionserkennung für HausRadar.

Eine Transition = Person verlässt Raum A (Exit-Event) + erscheint in Raum B
(Entry-Event) innerhalb von WINDOW_SEC.

Gelernte Verbindungen werden in config/learned_connections.json gespeichert.
Konfidenz = min(1.0, transition_count / CONFIDENCE_THRESHOLD)
Ab CONFIDENCE_THRESHOLD Transitionen gilt eine Verbindung als bestätigt.
"""

import json
import threading
import time
from pathlib import Path
from typing import List, Optional

WINDOW_SEC           = 8.0   # Zeitfenster Exit→Entry für eine Transition
CONFIDENCE_THRESHOLD = 10    # Transitionen für confidence=1.0
MAX_PENDING_EXITS    = 50    # Maximale offene Exit-Events

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "learned_connections.json"

_lock          = threading.Lock()
_pending_exits: List[dict] = []   # [{room_id, ts}]
_connections:   List[dict] = []   # persistierte Verbindungen
_pending_events: List[dict] = []  # transit events für WS-Broadcast


# ──────────────────────────────────────────────────────────────────────────────
# Initialisierung
# ──────────────────────────────────────────────────────────────────────────────

def load() -> None:
    """Lädt learned_connections.json beim Server-Start."""
    global _connections
    with _lock:
        if _CONFIG_PATH.exists():
            try:
                data = json.loads(_CONFIG_PATH.read_text())
                _connections = data if isinstance(data, list) else []
            except Exception:
                _connections = []
        else:
            _connections = []


def _save() -> None:
    """Speichert Verbindungen – muss unter _lock aufgerufen werden."""
    try:
        _CONFIG_PATH.write_text(json.dumps(_connections, indent=2))
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Öffentliche API (aufgerufen aus mqtt_service._detect_door_events)
# ──────────────────────────────────────────────────────────────────────────────

def record_exit(room_id: str) -> None:
    """Merkt sich, dass jemand Raum room_id gerade verlassen hat."""
    now = time.time()
    with _lock:
        _pending_exits.append({"room_id": room_id, "ts": now})
        cutoff = now - WINDOW_SEC
        while _pending_exits and _pending_exits[0]["ts"] < cutoff:
            del _pending_exits[0]
        if len(_pending_exits) > MAX_PENDING_EXITS:
            del _pending_exits[0]


def record_entry(room_id: str) -> Optional[dict]:
    """
    Prüft ob kurz zuvor jemand aus einem anderen Raum rausgegangen ist.
    Wenn ja → Transition verbuchen, Verbindung updaten, transit-Event erzeugen.
    Gibt den transit-Event-Dict zurück oder None.
    """
    now = time.time()
    cutoff = now - WINDOW_SEC

    with _lock:
        match = None
        for ex in reversed(_pending_exits):
            if ex["ts"] < cutoff:
                break
            if ex["room_id"] != room_id:
                match = ex
                break

        if match is None:
            return None

        room_a = match["room_id"]
        room_b = room_id
        cid    = _conn_id(room_a, room_b)

        conn = next((c for c in _connections if c["id"] == cid), None)
        if conn is None:
            conn = {
                "id":               cid,
                "room_a":           room_a,
                "room_b":           room_b,
                "transition_count": 0,
                "confidence":       0.0,
                "confirmed":        False,
                "ts_last":          now,
            }
            _connections.append(conn)

        conn["transition_count"] += 1
        conn["confidence"]        = round(
            min(1.0, conn["transition_count"] / CONFIDENCE_THRESHOLD), 2
        )
        conn["ts_last"] = now
        if conn["transition_count"] >= CONFIDENCE_THRESHOLD:
            conn["confirmed"] = True

        _save()

        event = {
            "type":      "transit",
            "from_room": room_a,
            "to_room":   room_b,
            "ts_ms":     int(now * 1000),
        }
        _pending_events.append(event)
        return event


def pop_events() -> List[dict]:
    """Gibt alle aufgelaufenen Transit-Events zurück und leert die Queue."""
    with _lock:
        evts = list(_pending_events)
        _pending_events.clear()
        return evts


def get_connections() -> List[dict]:
    with _lock:
        return list(_connections)


def delete_connection(cid: str) -> bool:
    with _lock:
        before = len(_connections)
        _connections[:] = [c for c in _connections if c["id"] != cid]
        if len(_connections) < before:
            _save()
            return True
        return False


def reset_connection(cid: str) -> bool:
    """Setzt Transitionszähler zurück ohne die Verbindung zu löschen."""
    with _lock:
        conn = next((c for c in _connections if c["id"] == cid), None)
        if conn is None:
            return False
        conn["transition_count"] = 0
        conn["confidence"]       = 0.0
        conn["confirmed"]        = False
        _save()
        return True


# ──────────────────────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ──────────────────────────────────────────────────────────────────────────────

def _conn_id(a: str, b: str) -> str:
    """Eindeutige ID für A↔B (bidirektional sortiert)."""
    return "__".join(sorted([a, b]))
