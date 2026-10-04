"""Tests for galaxy positions, distances, the nearest planet per resource and the Galaxy tab (pure)."""

import math

from nms_connector import galaxy, planets_view
from nms_connector.history import PlanetHistory

SYSTEM_98 = 0x620002925E80           # Euclid, region (-384, 2, -1755), system 98
SYSTEM_115 = 0x730002925E80          # same region, system 115


def key(x, y, z, system, galaxy_index=0):
    """A packed system key from region voxel, system index and galaxy."""
    return (x & 0xFFF) | (z & 0xFFF) << 12 | (y & 0xFF) << 24 | galaxy_index << 32 | system << 40


def test_region_and_distance_follow_the_packed_address():
    """The packed address gives the region voxel; distance is 400 ly per voxel step between regions, 0 inside
    one region, and undefined between galaxies."""
    assert galaxy.region(SYSTEM_98) == (-384, 2, -1755) and galaxy.system_index(SYSTEM_98) == 98
    a, b = key(-384, 2, -1755, 1), key(-381, 2, -1751, 7)
    assert galaxy.distance_ly(a, b) == 400 * 5                      # 3-4-5 triangle
    assert galaxy.distance_ly(SYSTEM_98, SYSTEM_115) == 0
    assert galaxy.distance_ly(a, key(-384, 2, -1755, 1, galaxy_index=1)) is None
    assert galaxy.distance_text(0) == "same region (< 400 ly)" and galaxy.distance_text(2000) == "~2,000 ly"
    assert galaxy.distance_text(None) == "other galaxy" and galaxy.distance_text(0, same_system=True) == "this system"


def test_systems_of_one_region_are_spread_but_stay_near_its_point():
    """Two systems of one region get different, stable map positions within SPREAD of the region's voxel, so
    they never cover each other on the map; the height is the region's."""
    p98, p115 = galaxy.map_position(SYSTEM_98), galaxy.map_position(SYSTEM_115)
    assert p98 != p115 and p98 == galaxy.map_position(SYSTEM_98)
    for p in (p98, p115):
        assert math.dist((p[0], p[2]), (-384, -1755)) <= galaxy.SPREAD + 1e-9 and p[1] == 2


def planet(name, index, system, common, uncommon, rare, extra=(), biome="Lush"):
    return {"name": name, "index": index, "system": system, "ua": system | (index + 1) << 52, "common": common,
            "uncommon": uncommon, "rare": rare, "extra": list(extra), "biome": biome}


def test_nearest_planet_per_resource_prefers_your_system_then_distance():
    """For each resource the planet in your own system wins (many systems share a region at distance 0), then
    the nearest region, then the system with more planets offering it; plants and gas count as resources."""
    near_region, far_region = key(-384, 2, -1755, 5), key(-370, 2, -1755, 9)
    systems = {
        SYSTEM_98: [planet("Here", 0, SYSTEM_98, "YELLOW2", "LUSH1", "LAND3", ["PLANT_LUSH"])],
        near_region: [planet("Near A", 0, near_region, "YELLOW2", "TOXIC1", "CATALYST1"),
                      planet("Near B", 1, near_region, "YELLOW2", "TOXIC1", "WATER1")],
        far_region: [planet("Far", 0, far_region, "RED2", "COLD1", "CAVE1")],
    }
    found = {e["resource"]: e for e in galaxy.nearest_by_resource(systems, SYSTEM_98, planets_view.planet_gas)}
    assert found["YELLOW2"]["planet"]["name"] == "Here"
    assert found["TOXIC1"]["system"] == near_region and found["TOXIC1"]["count"] == 2
    assert found["RED2"]["distance"] == 14 * 400
    assert found["PLANT_LUSH"]["planet"]["name"] == "Here" and found["GAS3"]["planet"]["name"] == "Here"
    no_origin = galaxy.nearest_by_resource(systems, None, planets_view.planet_gas)
    assert all(e["distance"] is None for e in no_origin)


class Live:
    status, error, current, current_source = "ok", None, None, "planets"
    current_system = SYSTEM_98


class Texts:
    def lookup(self, item_id):
        return {"en": item_id.title(), "local": item_id.title()}

    def icon_name(self, item_id):
        return None

    def text(self, key):
        return None


def test_galaxy_tab_maps_every_system_and_lists_the_nearest_resources(tmp_path):
    """The Galaxy tab draws every known system of your galaxy (you marked, bases highlighted), offers 'Open
    system map' for a point and lists the nearest planet per resource with clickable rows; systems in another
    galaxy are counted, not drawn."""
    history = PlanetHistory(tmp_path / "h.json")
    history.record([planet("Here", 0, SYSTEM_98, "YELLOW2", "LUSH1", "LAND3")], "t", SYSTEM_98)
    other_galaxy = key(10, 0, 10, 3, galaxy_index=1)
    visits = {SYSTEM_115: {"name": "Kayanis Majoris VIII", "planets": {}}, other_galaxy: {"name": None, "planets": {}}}
    ctx = planets_view.Context(Live(), history, visits, Texts(), None, bases=[{"name": "Home", "system": SYSTEM_115}])
    starmap, note, nearest = planets_view.galaxy_sections(ctx, SYSTEM_115)
    assert starmap["type"] == "starmap" and starmap["action"] == planets_view.OPEN_SYSTEM
    by_key = {p["key"]: p for p in starmap["points"]}
    assert set(by_key) == {f"{SYSTEM_98:x}", f"{SYSTEM_115:x}"} and starmap["selected_key"] == f"{SYSTEM_115:x}"
    assert by_key[f"{SYSTEM_98:x}"]["marker"] == "current"
    assert by_key[f"{SYSTEM_115:x}"]["color"] == planets_view.POINT_COLORS["bases"]
    assert starmap["bounds"] == galaxy.GALAXY_BOUNDS and starmap["center"]["label"] == "Galaxy centre"
    assert "1 known system(s) lie in other galaxies" in note["text"]
    assert nearest["row_action"] == planets_view.OPEN_SYSTEM and nearest["rows"][0][3] == "this system"
    assert set(nearest["row_keys"]) == {f"{SYSTEM_98:x}"}
    tabs = planets_view.systems_tabs(ctx, None)["tabs"]
    galaxy_tab = next(t for t in tabs if t["id"] == "galaxy")
    assert galaxy_tab["sections"][0]["id"] == planets_view.GALAXY_MAP_ID
