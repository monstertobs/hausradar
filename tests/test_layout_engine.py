"""Tests für das Floorplan-Auto-Layout (layout_engine).

Sichern das saubere Kachel-Verhalten ab:
  * manuell positionierte Räume werden eingefroren (Quelle der Wahrheit),
  * automatisch platzierte Nachbarn teilen sich Wände (kein Versatz, kein Gap),
  * gelernte Verbindungen verschieben bestehende Räume nicht.
"""

from app import layout_engine as le


def _room(rid, w_mm, h_mm, floorplan=None, doors=None):
    r = {"id": rid, "name": rid, "width_mm": w_mm, "height_mm": h_mm}
    if floorplan is not None:
        r["floorplan"] = floorplan
    if doors is not None:
        r["doors"] = doors
    return r


def test_leeres_layout():
    assert le.compute([]) == {}


def test_manuelle_koords_werden_eingefroren():
    """Räume mit floorplan-Koords kommen 1:1 zurück (nur normalisiert)."""
    rooms = [
        _room("a", 6000, 4500, {"x": 10, "y": 10, "width": 300, "height": 225}),
        _room("b", 4000, 1500, {"x": 320, "y": 10, "width": 200, "height": 75}),
    ]
    out = le.compute(rooms, [])
    assert out["a"]["x"] == 10 and out["a"]["y"] == 10
    assert out["b"]["x"] == 320 and out["b"]["y"] == 10


def test_auto_nachbar_teilt_wand_ohne_versatz():
    """Tür an rechter Wand → Nachbar dockt bündig an, gleiche Oberkante."""
    rooms = [
        _room("a", 6000, 4500, doors=[{"connects_to": "b", "wall": "right"}]),
        _room("b", 4000, 3000),
    ]
    out = le.compute(rooms, [])
    a, b = out["a"], out["b"]
    # bündig: kein Gap zwischen rechter Kante von a und linker Kante von b
    assert b["x"] == a["x"] + a["width"]
    # kein vertikaler Versatz: Oberkanten gleich
    assert b["y"] == a["y"]


def test_tuerposition_verschiebt_raum_nicht():
    """Egal wo die Tür in der Wand sitzt – die Raumkanten bleiben bündig."""
    base = _room("b", 4000, 3000)
    out_low = le.compute(
        [_room("a", 6000, 4500, doors=[{"connects_to": "b", "wall": "right",
                                        "position_mm": 200}]), base], [])
    out_high = le.compute(
        [_room("a", 6000, 4500, doors=[{"connects_to": "b", "wall": "right",
                                        "position_mm": 4000}]), base], [])
    # Türposition ändert die Raumplatzierung NICHT mehr (früherer Treppen-Bug)
    assert out_low["b"]["y"] == out_high["b"]["y"]


def test_gelernte_verbindung_verschiebt_bestehende_nicht():
    """Eine neu gelernte Verbindung darf manuelle Anker nicht verrücken."""
    rooms = [
        _room("a", 6000, 4500, {"x": 10, "y": 10, "width": 300, "height": 225}),
        _room("b", 4000, 3000, {"x": 320, "y": 10, "width": 200, "height": 150}),
    ]
    before = le.compute(rooms, [])
    after = le.compute(rooms, [{"room_a": "a", "room_b": "b"}])
    assert before == after


def test_unverbundener_raum_wird_platziert():
    """Ein Raum ohne Tür/Koords darf nicht verschwinden."""
    rooms = [
        _room("a", 6000, 4500, {"x": 10, "y": 10, "width": 300, "height": 225}),
        _room("solo", 3000, 3000),
    ]
    out = le.compute(rooms, [])
    assert "solo" in out
    assert out["solo"]["width"] > 0 and out["solo"]["height"] > 0


def test_fresh_ignoriert_manuelle_anker():
    """fresh=True berechnet neu, auch wenn floorplan-Koords existieren."""
    rooms = [
        _room("a", 6000, 4500, {"x": 500, "y": 500, "width": 300, "height": 225},
              doors=[{"connects_to": "b", "wall": "right"}]),
        _room("b", 4000, 3000, {"x": 900, "y": 700, "width": 200, "height": 150}),
    ]
    out = le.compute(rooms, [], fresh=True)
    a, b = out["a"], out["b"]
    # Neu platziert: a am Ursprung (PAD), b bündig rechts daneben
    assert a["x"] == le.PAD and a["y"] == le.PAD
    assert b["x"] == a["x"] + a["width"]
    assert b["y"] == a["y"]


def test_kollision_wird_aufgeloest():
    """Zwei Räume, die an derselben Wand andocken, dürfen sich nicht überlappen."""
    rooms = [
        _room("a", 6000, 4500, doors=[
            {"connects_to": "b", "wall": "right"},
            {"connects_to": "c", "wall": "right"},
        ]),
        _room("b", 4000, 3000),
        _room("c", 4000, 3000),
    ]
    out = le.compute(rooms, [], fresh=True)
    b, c = out["b"], out["c"]
    # b und c docken beide rechts an a an – c muss ausweichen
    overlap_x = min(b["x"] + b["width"],  c["x"] + c["width"])  - max(b["x"], c["x"])
    overlap_y = min(b["y"] + b["height"], c["y"] + c["height"]) - max(b["y"], c["y"])
    assert not (overlap_x > 1 and overlap_y > 1), f"b und c überlappen: {b} / {c}"


def test_tuer_gegenstueck_sync():
    """PATCH einer Tür richtet das Gegenstück im Nachbarraum fluchtend aus."""
    from app.api.calibrate import _sync_counterpart_door

    room_a = {
        "id": "a", "width_mm": 6000, "height_mm": 4500,
        "floorplan": {"x": 10, "y": 10, "width": 300, "height": 225},
        "doors": [{"id": "d1", "connects_to": "b", "wall": "right",
                   "position_mm": 2000, "width_mm": 900}],
    }
    room_b = {
        "id": "b", "width_mm": 4000, "height_mm": 4500,
        "floorplan": {"x": 310, "y": 10, "width": 200, "height": 225},
        "doors": [{"id": "d2", "connects_to": "a", "wall": "left",
                   "position_mm": 0, "width_mm": 800}],
    }
    rooms = [room_a, room_b]
    synced = _sync_counterpart_door(rooms, room_a, room_a["doors"][0])
    assert synced == "b"
    cp = room_b["doors"][0]
    # Breite übernommen, Position fluchtet: gleiche Wand-Skala (225px/4500mm)
    # → Türmitte a bei y=10+(2450/4500)*225 px muss Türmitte b entsprechen
    assert cp["width_mm"] == 900
    assert cp["position_mm"] == 2000   # gleiche Skala + gleiche y-Lage → gleiche Position


def test_tuer_sync_ohne_gegenstueck_ist_noop():
    from app.api.calibrate import _sync_counterpart_door
    room_a = {
        "id": "a", "width_mm": 6000, "height_mm": 4500,
        "floorplan": {"x": 10, "y": 10, "width": 300, "height": 225},
        "doors": [{"id": "d1", "connects_to": "b", "wall": "right",
                   "position_mm": 2000, "width_mm": 900}],
    }
    room_b = {"id": "b", "width_mm": 4000, "height_mm": 3000,
              "floorplan": {"x": 310, "y": 10, "width": 200, "height": 150},
              "doors": []}
    assert _sync_counterpart_door([room_a, room_b], room_a, room_a["doors"][0]) is None


def test_etagen_werden_getrennt_angeordnet():
    """Räume verschiedener Etagen überlappen nie und liegen nebeneinander."""
    rooms = [
        dict(_room("eg1", 6000, 4500), floor=0,
             doors=[{"connects_to": "eg2", "wall": "right"}]),
        dict(_room("eg2", 4000, 3000), floor=0),
        dict(_room("keller", 8000, 5000), floor=-1),
    ]
    out = le.compute(rooms, [], fresh=True)
    k, e1 = out["keller"], out["eg1"]
    # Keller (Etage -1) liegt links, EG-Gruppe rechts davon mit Abstand
    assert k["x"] < e1["x"]
    assert e1["x"] >= k["x"] + k["width"] + le.FLOOR_GUTTER - 1
    # EG-Räume bleiben Wand an Wand
    assert out["eg2"]["x"] == e1["x"] + e1["width"]


def test_treppen_tuer_zieht_keller_nicht_unters_eg():
    """Eine Tür zwischen Etagen (Treppe) darf die Gruppen nicht vermischen."""
    rooms = [
        dict(_room("flur", 4000, 1500), floor=0,
             doors=[{"connects_to": "keller", "wall": "bottom"}]),
        dict(_room("keller", 8000, 5000), floor=-1),
    ]
    out = le.compute(rooms, [], fresh=True)
    f, k = out["flur"], out["keller"]
    overlap_x = min(f["x"] + f["width"],  k["x"] + k["width"])  - max(f["x"], k["x"])
    overlap_y = min(f["y"] + f["height"], k["y"] + k["height"]) - max(f["y"], k["y"])
    assert not (overlap_x > 0 and overlap_y > 0)


def test_eine_etage_verhaelt_sich_wie_bisher():
    """Ohne floor-Feld ändert sich nichts am Anker-Verhalten."""
    rooms = [
        _room("a", 6000, 4500, {"x": 10, "y": 10, "width": 300, "height": 225}),
        _room("b", 4000, 1500, {"x": 320, "y": 10, "width": 200, "height": 75}),
    ]
    out = le.compute(rooms, [])
    assert out["a"]["x"] == 10 and out["b"]["x"] == 320
