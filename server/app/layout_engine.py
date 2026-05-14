"""
BFS-Auto-Layout für HausRadar.

Berechnet SVG-Floorplan-Koordinaten aus dem Verbindungsgraphen der Räume.
Berücksichtigt sowohl manuell kalibrierte Türen (rooms.json) als auch
automatisch gelernte Verbindungen (transition_detector).

Schreibt NICHT in rooms.json – gibt nur ein Layout-Dict zurück.
"""

import math
from typing import Dict, List, Optional, Tuple

SCALE = 0.05   # px / mm  (1 m → 50 px)
GAP   = 12     # px Lücke zwischen benachbarten Räumen
PAD   = 10     # px Außenabstand


def fp_size(room: dict) -> Tuple[int, int]:
    w = max(round(room.get("width_mm",  5000) * SCALE), 20)
    h = max(round(room.get("height_mm", 4000) * SCALE), 20)
    return w, h


def compute(rooms: List[dict], learned_connections: Optional[List[dict]] = None) -> dict:
    """
    Berechnet Floorplan-Positionen für alle Räume.

    Verbindungsquellen (beide werden genutzt):
      - Türen in rooms.json  (präzise Wandposition bekannt)
      - learned_connections  (nur Raumpaare bekannt, keine Wand)

    Rückgabe: dict room_id → {"x", "y", "width", "height"}
    (direkte SVG-Pixel, keine Änderung an rooms.json)
    """
    if not rooms:
        return {}

    room_map: Dict[str, dict] = {r["id"]: r for r in rooms}

    # ── Verbindungsgraph aufbauen ────────────────────────────────────────────
    # edges: room_id → list of (neighbor_id, wall, door_pos_mm, door_w_mm)
    # Für gelernte Verbindungen: wall=None (kein Wandbezug)
    edges: Dict[str, List[tuple]] = {r["id"]: [] for r in rooms}

    for room in rooms:
        for door in room.get("doors", []):
            nid = (door.get("connects_to") or "").strip()
            if nid and nid in room_map:
                edges[room["id"]].append((
                    nid,
                    door.get("wall", "right"),
                    door.get("position_mm", 0),
                    door.get("width_mm", 800),
                ))

    # Gelernte Verbindungen hinzufügen (bidirektional, nur wenn noch keine Tür existiert)
    for conn in (learned_connections or []):
        a, b = conn.get("room_a"), conn.get("room_b")
        if not a or not b or a not in room_map or b not in room_map:
            continue
        already = any(nb == b for nb, *_ in edges[a])
        if not already:
            edges[a].append((b, None, None, None))
            edges[b].append((a, None, None, None))

    # ── BFS-Platzierung ──────────────────────────────────────────────────────
    placed:  Dict[str, Tuple[int, int]] = {}
    visited: set = set()

    first_id = rooms[0]["id"]
    placed[first_id] = (PAD, PAD)
    visited.add(first_id)
    queue = [first_id]

    while queue:
        rid  = queue.pop(0)
        room = room_map[rid]
        rx, ry = placed[rid]
        rw, rh = fp_size(room)

        for nid, wall, door_pos_mm, door_w_mm in edges[rid]:
            if nid in visited:
                continue

            neighbor = room_map[nid]
            nw, nh   = fp_size(neighbor)

            if wall is not None and door_pos_mm is not None:
                # Tür mit Wandbezug: Türmitte im Nachbar ausrichten
                door_center = door_pos_mm * SCALE + (door_w_mm or 800) * SCALE / 2
                if wall == "right":
                    nx = rx + rw + GAP
                    ny = ry + door_center - nh / 2
                elif wall == "left":
                    nx = rx - GAP - nw
                    ny = ry + door_center - nh / 2
                elif wall == "bottom":
                    ny = ry + rh + GAP
                    nx = rx + door_center - nw / 2
                elif wall == "top":
                    ny = ry - GAP - nh
                    nx = rx + door_center - nw / 2
                else:
                    nx = rx + rw + GAP
                    ny = ry
            else:
                # Gelernte Verbindung ohne Wandbezug: rechts platzieren
                nx = rx + rw + GAP
                ny = ry + (rh - nh) / 2   # vertikal zentriert

            placed[nid] = (round(nx), round(ny))
            visited.add(nid)
            queue.append(nid)

    # ── Unverbundene Räume unterhalb anordnen ────────────────────────────────
    if placed:
        max_y = max(
            y + fp_size(room_map[r])[1]
            for r, (x, y) in placed.items()
        )
    else:
        max_y = PAD

    cur_x = PAD
    for room in rooms:
        if room["id"] not in placed:
            nw, nh = fp_size(room)
            placed[room["id"]] = (cur_x, round(max_y + GAP * 3))
            cur_x += nw + GAP

    # ── Normalisieren (min_x = PAD, min_y = PAD) ─────────────────────────────
    min_x = min(x for x, _ in placed.values())
    min_y = min(y for _, y in placed.values())
    shift_x = PAD - min_x
    shift_y = PAD - min_y
    placed = {rid: (x + shift_x, y + shift_y) for rid, (x, y) in placed.items()}

    # ── Rückgabe ─────────────────────────────────────────────────────────────
    result = {}
    for room in rooms:
        rid = room["id"]
        if rid not in placed:
            continue
        fx, fy = placed[rid]
        fw, fh = fp_size(room)
        result[rid] = {"x": fx, "y": fy, "width": fw, "height": fh}

    return result


def layout_changed(old_layout: dict, new_layout: dict, threshold_px: float = 2.0) -> bool:
    """Gibt True zurück wenn sich mindestens ein Raum um mehr als threshold_px verschoben hat."""
    for rid, new in new_layout.items():
        old = old_layout.get(rid)
        if old is None:
            return True
        if (math.fabs(new["x"] - old["x"]) > threshold_px or
                math.fabs(new["y"] - old["y"]) > threshold_px):
            return True
    return False
