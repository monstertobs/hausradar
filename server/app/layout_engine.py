"""
BFS-Auto-Layout für HausRadar.

Berechnet SVG-Floorplan-Koordinaten aus dem Verbindungsgraphen der Räume.
Berücksichtigt sowohl manuell kalibrierte Türen (rooms.json) als auch
automatisch gelernte Verbindungen (transition_detector).

Designprinzip (NEU):
  * Räume teilen sich Wände (GAP = 0) statt frei zu schweben.
  * Nachbarn werden an der GEMEINSAMEN WAND ausgerichtet, nicht an der
    Türmitte. Die Türöffnung selbst wird in floorplan.js entlang der Wand
    gezeichnet – ihre Position verschiebt den Raum also nicht mehr.
  * Manuell gesetzte floorplan-Koordinaten (rooms.json / "Layout bearbeiten")
    sind die QUELLE DER WAHRHEIT: solche Räume werden eingefroren und dienen
    als Anker. Nur Räume OHNE manuelle Position werden automatisch platziert.
  * Dadurch ist das Ergebnis stabil und springt nicht bei jedem Lern-Update.

Schreibt NICHT in rooms.json – gibt nur ein Layout-Dict zurück.
"""

import math
from typing import Dict, List, Optional, Tuple

SCALE        = 0.05   # px / mm  (1 m → 50 px)
GAP          = 0      # px Lücke zwischen benachbarten Räumen (0 = gemeinsame Wand)
PAD          = 10     # px Außenabstand
FLOOR_GUTTER = 50     # px Abstand zwischen Etagen-Gruppen


def fp_size(room: dict) -> Tuple[int, int]:
    w = max(round(room.get("width_mm",  5000) * SCALE), 20)
    h = max(round(room.get("height_mm", 4000) * SCALE), 20)
    return w, h


def _has_manual_pos(room: dict) -> bool:
    """True, wenn der Raum in rooms.json eine echte floorplan-Position hat."""
    fp = room.get("floorplan")
    return isinstance(fp, dict) and "x" in fp and "y" in fp


def _overlaps(ax: float, ay: float, aw: float, ah: float,
              bx: float, by: float, bw: float, bh: float,
              tol: float = 0.5) -> bool:
    """True wenn sich zwei Rechtecke flächig überlappen (Kanten-Berührung ok)."""
    return (ax + tol < bx + bw and bx + tol < ax + aw and
            ay + tol < by + bh and by + tol < ay + ah)


def _resolve_overlap(nx: float, ny: float, nw: int, nh: int, wall: str,
                     placed: Dict[str, Tuple[int, int]],
                     sizes: Dict[str, Tuple[int, int]]) -> Tuple[float, float]:
    """
    Verschiebt einen neu zu platzierenden Raum entlang der gemeinsamen Wand,
    bis er keinen bereits platzierten Raum mehr überlappt.

    Bei left/right-Andocken wird vertikal geschoben, bei top/bottom horizontal –
    so bleibt die gemeinsame Wand erhalten.
    """
    def collides(x: float, y: float) -> bool:
        return any(
            _overlaps(x, y, nw, nh, px, py, *sizes[rid])
            for rid, (px, py) in placed.items()
        )

    if not collides(nx, ny):
        return nx, ny

    step = 10
    for i in range(1, 121):
        for sign in (1, -1):
            off = sign * i * step
            if wall in ("top", "bottom"):
                cx, cy = nx + off, ny
            else:
                cx, cy = nx, ny + off
            if not collides(cx, cy):
                return cx, cy
    # Kein freier Platz gefunden – Original behalten (besser als Endlosschleife)
    return nx, ny


def compute(rooms: List[dict], learned_connections: Optional[List[dict]] = None,
            fresh: bool = False) -> dict:
    """
    Berechnet Floorplan-Positionen für alle Räume.

    Räume werden nach Etage (room["floor"], Standard 0) gruppiert: jede Etage
    wird unabhängig layoutet und die Gruppen nebeneinander angeordnet
    (aufsteigend sortiert: Keller links, dann EG, dann Obergeschosse).
    Türen/Verbindungen zwischen Etagen (Treppen) beeinflussen die Platzierung
    nicht – sonst würde der Keller unters Erdgeschoss geschoben.

    fresh=True ignoriert vorhandene floorplan-Koordinaten und berechnet das
    Layout komplett neu (für den expliziten "Auto-Layout"-Button). Im
    Standardmodus (fresh=False) sind manuelle Positionen eingefrorene Anker.

    Rückgabe: dict room_id → {"x", "y", "width", "height"}
    (direkte SVG-Pixel, keine Änderung an rooms.json)
    """
    if not rooms:
        return {}

    floors: dict = {}
    for r in rooms:
        floors.setdefault(int(r.get("floor", 0) or 0), []).append(r)

    # Eine Etage → bisheriges Verhalten (Anker bleiben exakt erhalten)
    if len(floors) == 1:
        return _compute_floor(rooms, learned_connections, fresh)

    result: dict = {}
    offset_x = 0
    for fl in sorted(floors):
        group = floors[fl]
        ids   = {r["id"] for r in group}
        conns = [c for c in (learned_connections or [])
                 if c.get("room_a") in ids and c.get("room_b") in ids]
        sub = _compute_floor(group, conns, fresh)
        if not sub:
            continue
        # Gruppe auf den eigenen Etagen-Bereich verschieben
        min_x = min(v["x"] for v in sub.values())
        min_y = min(v["y"] for v in sub.values())
        max_x = 0
        for rid, v in sub.items():
            x = v["x"] - min_x + PAD + offset_x
            y = v["y"] - min_y + PAD
            result[rid] = {"x": x, "y": y, "width": v["width"], "height": v["height"]}
            max_x = max(max_x, x + v["width"])
        offset_x = max_x - PAD + FLOOR_GUTTER

    return result


def _compute_floor(rooms: List[dict], learned_connections: Optional[List[dict]] = None,
                   fresh: bool = False) -> dict:
    """Layoutet die Räume EINER Etage (Türen-BFS, Wand an Wand, Kollisionscheck)."""
    if not rooms:
        return {}

    room_map: Dict[str, dict] = {r["id"]: r for r in rooms}

    # ── Verbindungsgraph aufbauen ────────────────────────────────────────────
    # edges: room_id → list of (neighbor_id, wall)
    # wall bestimmt nur noch die RICHTUNG (rechts/links/oben/unten),
    # nicht mehr einen vertikalen Versatz. Gelernte Verbindungen: wall=None.
    edges: Dict[str, List[Tuple[str, Optional[str]]]] = {r["id"]: [] for r in rooms}

    for room in rooms:
        for door in room.get("doors", []):
            nid = (door.get("connects_to") or "").strip()
            if nid and nid in room_map:
                edges[room["id"]].append((nid, door.get("wall", "right")))

    for conn in (learned_connections or []):
        a, b = conn.get("room_a"), conn.get("room_b")
        if not a or not b or a not in room_map or b not in room_map:
            continue
        if not any(nb == b for nb, _ in edges[a]):
            edges[a].append((b, None))
            edges[b].append((a, None))

    placed:  Dict[str, Tuple[int, int]] = {}
    visited: set = set()
    queue:   List[str] = []

    # Raumgrößen einmalig berechnen (auch für Kollisionsprüfung)
    sizes: Dict[str, Tuple[int, int]] = {r["id"]: fp_size(r) for r in rooms}

    # ── Anker: manuell positionierte Räume einfrieren ───────────────────────
    # Sie werden 1:1 übernommen und seeden die BFS für ihre Nachbarn.
    # Im fresh-Modus werden Anker ignoriert – alles wird neu platziert.
    for room in rooms:
        if not fresh and _has_manual_pos(room):
            fp = room["floorplan"]
            placed[room["id"]] = (round(fp["x"]), round(fp["y"]))
            visited.add(room["id"])
            queue.append(room["id"])

    # Kein manueller Anker → ersten Raum als Ursprung setzen.
    if not queue:
        first_id = rooms[0]["id"]
        placed[first_id] = (PAD, PAD)
        visited.add(first_id)
        queue.append(first_id)

    # ── BFS-Platzierung: gemeinsame Wand, ausgerichtete Kanten ──────────────
    while queue:
        rid = queue.pop(0)
        rx, ry = placed[rid]
        rw, rh = fp_size(room_map[rid])

        for nid, wall in edges[rid]:
            if nid in visited:
                continue
            nw, nh = fp_size(room_map[nid])

            w = wall or "right"   # gelernte Verbindung → rechts andocken
            if w == "right":
                nx, ny = rx + rw + GAP, ry            # gemeinsame rechte Wand, Oberkanten bündig
            elif w == "left":
                nx, ny = rx - GAP - nw, ry
            elif w == "bottom":
                nx, ny = rx, ry + rh + GAP            # gemeinsame Unterwand, linke Kanten bündig
            elif w == "top":
                nx, ny = rx, ry - GAP - nh
            else:
                nx, ny = rx + rw + GAP, ry

            nx, ny = _resolve_overlap(nx, ny, nw, nh, w, placed, sizes)
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
            placed[room["id"]] = (cur_x, round(max_y + GAP + PAD))
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
