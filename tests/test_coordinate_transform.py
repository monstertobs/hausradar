"""Tests für server/app/coordinate_transform.py"""
import math
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from app.coordinate_transform import (
    transform_sensor_to_room,
    transform_room_to_floorplan,
    is_target_inside_room,
    detect_zone,
    full_transform,
)


# ---------------------------------------------------------------------------
# Hilfsobjekte
# ---------------------------------------------------------------------------

def _sensor(x=0, y=0, rotation=0, sid="s1", room_id="r1"):
    return {
        "id": sid, "room_id": room_id,
        "x_mm": x, "y_mm": y,
        "rotation_deg": rotation,
        "mount_height_mm": 2200,
        "enabled": True,
    }


def _room(w=6000, h=4000, fp=None, zones=None):
    return {
        "id": "r1", "name": "Testraum",
        "width_mm": w, "height_mm": h,
        "floorplan": fp or {"x": 0, "y": 0, "width": 300, "height": 200},
        "zones": zones or [],
    }


def _target(x=0, y=0):
    return {"x_mm": x, "y_mm": y}


def approx(val, expected, tol=0.01):
    """Toleranzvergleich auf 0,01 mm."""
    return abs(val - expected) < tol


# ---------------------------------------------------------------------------
# transform_sensor_to_room – rotation_deg = 0
# ---------------------------------------------------------------------------

class TestRotation0:
    """Standardmontage: Sensor an y=0-Wand, zeigt in +y-Richtung."""

    def test_target_straight_ahead(self):
        s = _sensor(x=3000, y=0, rotation=0)
        r = transform_sensor_to_room(s, _target(0, 2000))
        assert approx(r["x_mm"], 3000)
        assert approx(r["y_mm"], 2000)

    def test_target_to_the_right(self):
        s = _sensor(x=3000, y=0, rotation=0)
        r = transform_sensor_to_room(s, _target(500, 2000))
        assert approx(r["x_mm"], 3500)
        assert approx(r["y_mm"], 2000)

    def test_target_to_the_left(self):
        s = _sensor(x=3000, y=0, rotation=0)
        r = transform_sensor_to_room(s, _target(-500, 2000))
        assert approx(r["x_mm"], 2500)
        assert approx(r["y_mm"], 2000)

    def test_target_at_sensor_position(self):
        s = _sensor(x=3000, y=0, rotation=0)
        r = transform_sensor_to_room(s, _target(0, 0))
        assert approx(r["x_mm"], 3000)
        assert approx(r["y_mm"], 0)

    def test_sensor_centered_on_wall(self):
        """Sensor mittig an der oberen Wand (y=0), Mitte des Raums."""
        s = _sensor(x=3000, y=0, rotation=0)
        r = transform_sensor_to_room(s, _target(0, 4000))
        # Geradeaus = Raummitte x, volle Tiefe y
        assert approx(r["x_mm"], 3000)
        assert approx(r["y_mm"], 4000)

    def test_sensor_on_bottom_wall_rotation_180(self):
        """Sensor an unterer Wand (y=height), zeigt in –y-Richtung."""
        s = _sensor(x=3000, y=4000, rotation=180)
        r = transform_sensor_to_room(s, _target(0, 2000))
        # Vorwärts = –y-Richtung → Raum-y sinkt
        assert approx(r["x_mm"], 3000)
        assert approx(r["y_mm"], 2000)  # 4000 – 2000 = 2000

    def test_all_sensor_coordinates_translate(self):
        s = _sensor(x=1000, y=2000, rotation=0)
        r = transform_sensor_to_room(s, _target(200, 300))
        assert approx(r["x_mm"], 1200)
        assert approx(r["y_mm"], 2300)


# ---------------------------------------------------------------------------
# transform_sensor_to_room – rotation_deg = 90
# ---------------------------------------------------------------------------

class TestRotation90:
    """Sensor an x=0-Wand, zeigt in +x-Richtung."""

    def test_target_straight_ahead(self):
        """Vorwärts = +x im Raum."""
        s = _sensor(x=0, y=2000, rotation=90)
        r = transform_sensor_to_room(s, _target(0, 2000))
        assert approx(r["x_mm"], 2000)
        assert approx(r["y_mm"], 2000)

    def test_target_to_sensor_right_is_minus_y(self):
        """Sensor zeigt in +x: rechts vom Sensor = –y im Raum."""
        s = _sensor(x=0, y=2000, rotation=90)
        r = transform_sensor_to_room(s, _target(1000, 0))
        assert approx(r["x_mm"], 0)
        assert approx(r["y_mm"], 1000)  # 2000 – 1000 = 1000

    def test_target_to_sensor_left_is_plus_y(self):
        """Sensor zeigt in +x: links vom Sensor = +y im Raum."""
        s = _sensor(x=0, y=2000, rotation=90)
        r = transform_sensor_to_room(s, _target(-500, 0))
        assert approx(r["x_mm"], 0)
        assert approx(r["y_mm"], 2500)  # 2000 + 500 = 2500

    def test_diagonal_target(self):
        """Diagonales Ziel bei 90°-Sensor."""
        s = _sensor(x=0, y=3000, rotation=90)
        r = transform_sensor_to_room(s, _target(1000, 2000))
        # x_rel = 1000*cos90 + 2000*sin90 = 0 + 2000 = 2000
        # y_rel = –1000*sin90 + 2000*cos90 = –1000 + 0 = –1000
        assert approx(r["x_mm"], 2000)
        assert approx(r["y_mm"], 2000)  # 3000 – 1000


# ---------------------------------------------------------------------------
# transform_sensor_to_room – weitere Rotationen
# ---------------------------------------------------------------------------

class TestOtherRotations:
    def test_rotation_270_forward_is_minus_x(self):
        """Sensor an rechter Wand (x=width), zeigt in –x-Richtung."""
        s = _sensor(x=6000, y=2000, rotation=270)
        r = transform_sensor_to_room(s, _target(0, 2000))
        # sin270=–1, cos270=0
        # x_rel = 0*0 + 2000*(–1) = –2000
        # y_rel = –0*(–1) + 2000*0 = 0
        assert approx(r["x_mm"], 4000)
        assert approx(r["y_mm"], 2000)

    def test_rotation_45(self):
        """45°-Diagonale – symmetrischer Geradeausblick."""
        s = _sensor(x=0, y=0, rotation=45)
        r = transform_sensor_to_room(s, _target(0, 1000))
        c = math.cos(math.radians(45))
        # x_rel = 0*c + 1000*c  = 1000*c
        # y_rel = 0   + 1000*c  = 1000*c
        assert approx(r["x_mm"], 1000 * c, tol=0.1)
        assert approx(r["y_mm"], 1000 * c, tol=0.1)

    def test_rotation_is_float_compatible(self):
        """rotation_deg darf float sein."""
        s = _sensor(x=1000, y=1000, rotation=0.0)
        r = transform_sensor_to_room(s, _target(0, 500))
        assert approx(r["x_mm"], 1000)
        assert approx(r["y_mm"], 1500)


# ---------------------------------------------------------------------------
# transform_room_to_floorplan
# ---------------------------------------------------------------------------

class TestTransformRoomToFloorplan:
    def test_origin_maps_to_floorplan_origin(self):
        room = _room(w=6000, h=4000, fp={"x": 10, "y": 20, "width": 300, "height": 200})
        fp = transform_room_to_floorplan(room, 0, 0)
        assert approx(fp["x"], 10)
        assert approx(fp["y"], 20)

    def test_far_corner_maps_to_floorplan_far_corner(self):
        room = _room(w=6000, h=4000, fp={"x": 10, "y": 20, "width": 300, "height": 200})
        fp = transform_room_to_floorplan(room, 6000, 4000)
        assert approx(fp["x"], 310)  # 10 + 300
        assert approx(fp["y"], 220)  # 20 + 200

    def test_center_maps_correctly(self):
        room = _room(w=4000, h=2000, fp={"x": 0, "y": 0, "width": 200, "height": 100})
        fp = transform_room_to_floorplan(room, 2000, 1000)
        assert approx(fp["x"], 100)
        assert approx(fp["y"], 50)

    def test_scale_factor_applied(self):
        """Bei 6m×4m Raum → 300×200 px: Skala 0.05 px/mm."""
        room = _room(w=6000, h=4000, fp={"x": 0, "y": 0, "width": 300, "height": 200})
        fp = transform_room_to_floorplan(room, 1000, 1000)
        assert approx(fp["x"], 50.0)   # 1000 * 300/6000
        assert approx(fp["y"], 50.0)   # 1000 * 200/4000

    def test_non_zero_floorplan_offset(self):
        room = _room(fp={"x": 100, "y": 150, "width": 200, "height": 100})
        fp = transform_room_to_floorplan(room, 0, 0)
        assert approx(fp["x"], 100)
        assert approx(fp["y"], 150)


# ---------------------------------------------------------------------------
# is_target_inside_room
# ---------------------------------------------------------------------------

class TestIsTargetInsideRoom:
    def test_center_is_inside(self):
        room = _room(w=6000, h=4000)
        assert is_target_inside_room(room, 3000, 2000) is True

    def test_origin_corner_is_inside(self):
        room = _room(w=6000, h=4000)
        assert is_target_inside_room(room, 0, 0) is True

    def test_far_corner_is_inside(self):
        room = _room(w=6000, h=4000)
        assert is_target_inside_room(room, 6000, 4000) is True

    def test_negative_x_is_outside(self):
        room = _room(w=6000, h=4000)
        assert is_target_inside_room(room, -1, 2000) is False

    def test_negative_y_is_outside(self):
        room = _room(w=6000, h=4000)
        assert is_target_inside_room(room, 3000, -1) is False

    def test_x_exceeds_width_is_outside(self):
        room = _room(w=6000, h=4000)
        assert is_target_inside_room(room, 6001, 2000) is False

    def test_y_exceeds_height_is_outside(self):
        room = _room(w=6000, h=4000)
        assert is_target_inside_room(room, 3000, 4001) is False

    def test_sensor_forward_outside_room(self):
        """Sensor an Wand, Ziel mit negativem y (hinter Wand) → außerhalb."""
        s = _sensor(x=3000, y=0, rotation=0)
        r = transform_sensor_to_room(s, _target(0, -500))
        room = _room(w=6000, h=4000)
        assert is_target_inside_room(room, r["x_mm"], r["y_mm"]) is False


# ---------------------------------------------------------------------------
# detect_zone
# ---------------------------------------------------------------------------

class TestDetectZone:
    def _room_with_zones(self):
        zones = [
            {"id": "sofa",  "name": "Sofa",  "x_mm": 3500, "y_mm": 2500,
             "width_mm": 2000, "height_mm": 1500},
            {"id": "tv",    "name": "TV",    "x_mm":  500, "y_mm":  500,
             "width_mm": 2000, "height_mm": 1500},
        ]
        return _room(w=6000, h=4000, zones=zones)

    def test_point_in_sofa_zone(self):
        room = self._room_with_zones()
        assert detect_zone(room, 4000, 3000) == "sofa"

    def test_point_in_tv_zone(self):
        room = self._room_with_zones()
        assert detect_zone(room, 1000, 1000) == "tv"

    def test_point_in_no_zone(self):
        room = self._room_with_zones()
        assert detect_zone(room, 3000, 3000) is None

    def test_point_outside_room_not_in_zone(self):
        room = self._room_with_zones()
        assert detect_zone(room, -100, -100) is None

    def test_zone_edge_is_included(self):
        """Genau auf der Zonengrenze zählt als darin."""
        room = self._room_with_zones()
        assert detect_zone(room, 3500, 2500) == "sofa"

    def test_first_matching_zone_wins(self):
        """Überlappende Zonen: erste in der Liste gewinnt."""
        zones = [
            {"id": "zone_a", "name": "A", "x_mm": 0,    "y_mm": 0,
             "width_mm": 3000, "height_mm": 3000},
            {"id": "zone_b", "name": "B", "x_mm": 1000, "y_mm": 1000,
             "width_mm": 1000, "height_mm": 1000},
        ]
        room = _room(zones=zones)
        assert detect_zone(room, 1500, 1500) == "zone_a"

    def test_no_zones_configured(self):
        room = _room(zones=[])
        assert detect_zone(room, 3000, 2000) is None


# ---------------------------------------------------------------------------
# full_transform – kombinierter Durchlauf
# ---------------------------------------------------------------------------

class TestFullTransform:
    def _setup(self):
        zones = [
            {"id": "mitte", "name": "Mitte", "x_mm": 2000, "y_mm": 1000,
             "width_mm": 2000, "height_mm": 2000},
        ]
        room   = _room(w=6000, h=4000,
                       fp={"x": 0, "y": 0, "width": 300, "height": 200},
                       zones=zones)
        sensor = _sensor(x=3000, y=0, rotation=0)
        return sensor, room

    def test_target_inside_with_zone(self):
        sensor, room = self._setup()
        result = full_transform(sensor, room, _target(0, 2000))
        assert result["inside_room"] is True
        assert result["zone_id"] == "mitte"
        assert approx(result["room_x_mm"], 3000)
        assert approx(result["room_y_mm"], 2000)

    def test_target_inside_without_zone(self):
        sensor, room = self._setup()
        result = full_transform(sensor, room, _target(2900, 100))
        # Raum x=3000+2900=5900, y=100 → außerhalb Zone
        assert result["inside_room"] is True
        assert result["zone_id"] is None

    def test_target_outside_room(self):
        sensor, room = self._setup()
        result = full_transform(sensor, room, _target(0, -500))
        assert result["inside_room"] is False
        assert result["zone_id"] is None

    def test_floorplan_coords_computed(self):
        sensor, room = self._setup()
        result = full_transform(sensor, room, _target(0, 2000))
        # room (3000, 2000) → fp (3000*300/6000, 2000*200/4000) = (150, 100)
        assert approx(result["floorplan_x"], 150)
        assert approx(result["floorplan_y"], 100)

    def test_rotation_90_full_pipeline(self):
        """Ende-zu-Ende-Test mit 90°-Rotation."""
        zones = [{"id": "ecke", "name": "Ecke", "x_mm": 0, "y_mm": 0,
                  "width_mm": 1500, "height_mm": 1500}]
        room   = _room(w=4000, h=4000,
                       fp={"x": 10, "y": 10, "width": 200, "height": 200},
                       zones=zones)
        sensor = _sensor(x=0, y=2000, rotation=90)
        result = full_transform(sensor, room, _target(0, 1000))
        # x_rel = 1000*sin90 = 1000 → room x = 1000
        # y_rel = 1000*cos90 = 0    → room y = 2000
        assert approx(result["room_x_mm"], 1000)
        assert approx(result["room_y_mm"], 2000)
        assert result["inside_room"] is True
        assert result["zone_id"] is None  # (1000, 2000) liegt nicht in (0..1500, 0..1500)

    def test_real_config_wohnzimmer(self):
        """Integration: echte Config aus rooms.json / sensors.json."""
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
        from app.config import load_rooms, load_sensors
        rooms   = load_rooms()
        sensors = load_sensors(rooms)
        room_map   = {r["id"]: r for r in rooms}
        sensor_map = {s["id"]: s for s in sensors}

        s = sensor_map["radar_wohnzimmer"]
        r = room_map["wohnzimmer"]
        result = full_transform(s, r, {"x_mm": 0, "y_mm": 2000})

        assert result["inside_room"] is True
        assert approx(result["room_x_mm"], 3000)
        assert approx(result["room_y_mm"], 2000)
