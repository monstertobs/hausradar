"""Tests für die automatische Raumform-Erkennung (M25, auto_calibration.suggest_room_shape)."""

import random

from app import auto_calibration as ac


ROOM   = {"id": "wz", "width_mm": 6000, "height_mm": 4500}
SENSOR = {"id": "s1", "rotation_deg": 0, "x_mm": 3000, "y_mm": 0}


def _feed_l_shape(sensor_id, n=2000, seed=42):
    """Simuliert Bewegung in einem L-Raum: links volle Tiefe, rechts nur bis 2500mm."""
    rng = random.Random(seed)
    ac.reset(sensor_id)
    for _ in range(n):
        room_x = rng.uniform(200, 5800)
        max_y  = 4100 if room_x < 4000 else 2100   # rechter Teil flacher (L-Form)
        room_y = rng.uniform(300, max_y)
        # Raumkoordinaten → Sensorkoordinaten (rotation 0, sensor bei x=3000,y=0)
        ac.update(sensor_id, room_x - 3000, room_y)


def _feed_rectangle(sensor_id, n=2000, seed=7):
    rng = random.Random(seed)
    ac.reset(sensor_id)
    for _ in range(n):
        ac.update(sensor_id, rng.uniform(200, 5800) - 3000, rng.uniform(300, 4100))


def teardown_function():
    ac.reset("shape-l")
    ac.reset("shape-rect")
    ac.reset("shape-few")


def test_l_form_wird_erkannt():
    _feed_l_shape("shape-l")
    s = ac.suggest_room_shape("shape-l", ROOM, SENSOR)
    assert s is not None
    assert s["segments"] >= 2
    pts = s["shape_points"]
    assert len(pts) >= 6                      # L-Form braucht mind. 6 Ecken
    assert pts[0] == [0, 0] and pts[1] == [6000, 0]
    depths = [p[1] for p in pts if p[1] > 0]
    # Links tief (~4500), rechts flach (~2500) – beide Tiefen müssen vorkommen
    assert any(d > 3800 for d in depths), f"tiefer Teil fehlt: {pts}"
    assert any(d < 3200 for d in depths), f"flacher Teil fehlt: {pts}"


def test_rechteck_liefert_kein_polygon():
    _feed_rectangle("shape-rect")
    assert ac.suggest_room_shape("shape-rect", ROOM, SENSOR) is None


def test_zu_wenig_daten_liefert_none():
    ac.reset("shape-few")
    for i in range(50):
        ac.update("shape-few", 0, 1000)
    assert ac.suggest_room_shape("shape-few", ROOM, SENSOR) is None
