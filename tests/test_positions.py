"""Tests for the PROTOTYPE star positions: the galaxy map camera, lines of sight that meet at a star, star fixes,
naming them, and exact distances (positions.py, history, galaxy, planets_view, the plugin's action)."""

import json
import math
import struct

from nms_connector import galaxy, planets_view, positions
from nms_connector.history import PlanetHistory

DELTA_SOL = 0x0620002925E80               # region (-384, 2, -1755), system 0x062 (2026-10-05)
KAYANA = 0x0B50002925E80
DS_POS = (-383.7669, 1.886, -1755.0291)   # Delta Sol from 4 intersecting lines of sight, 2026-10-05
KAYANA_POS = (-384.1492, 1.8498, -1755.1169)   # Kayana XIV: the map said 157 LJ from Delta Sol


def axes_for(forward):
    """Screen half-axes (PDX, PDY) whose cross product is `forward` (the game's layout: right, down)."""
    f = positions._norm(forward)
    helper = (0.0, 1.0, 0.0) if abs(f[1]) < 0.9 else (1.0, 0.0, 0.0)
    right = positions._norm((helper[1] * f[2] - helper[2] * f[1], helper[2] * f[0] - helper[0] * f[2],
                             helper[0] * f[1] - helper[1] * f[0]))
    down = (f[1] * right[2] - f[2] * right[1], f[2] * right[0] - f[0] * right[2], f[0] * right[1] - f[1] * right[0])
    pdx, pdy = tuple(1.468 * c for c in right), tuple(0.828 * c for c in down)
    got = positions.forward_of(pdx, pdy)
    return (pdx, pdy) if all(abs(a - b) < 1e-6 for a, b in zip(got, f)) else (pdy, pdx)


def lock(star, direction, back=0.2):
    """A camera locked on `star`, looking along `direction` from `back` region units away."""
    f = positions._norm(direction)
    return {"eye": tuple(round(s - back * c, 5) for s, c in zip(star, f)), "forward": f}


class FakeGame:
    """Memory with the camera block: gTracePDX, gTracePDY and gGalacticScale names, values 0x20 after each."""

    def __init__(self, names=True):
        self.base = 0x2E9591F0000
        self.buf = bytearray(0x4000)
        self.eye_name = 0x1000
        self.buf[self.eye_name:self.eye_name + 16] = positions.GALACTIC_NAME
        if names:
            self.buf[self.eye_name - 0x240:self.eye_name - 0x240 + 10] = positions.PDX_NAME
            self.buf[self.eye_name - 0x1E0:self.eye_name - 0x1E0 + 10] = positions.PDY_NAME

    def look(self, camera):
        pdx, pdy = axes_for(camera["forward"])
        struct.pack_into("<3f", self.buf, self.eye_name - 0x240 + 0x20, *pdx)
        struct.pack_into("<3f", self.buf, self.eye_name - 0x1E0 + 0x20, *pdy)
        struct.pack_into("<3f", self.buf, self.eye_name + 0x20, *(c / 100 for c in camera["eye"]))

    def read(self, address, size):
        off = address - self.base
        return bytes(self.buf[off:off + size]) if 0 <= off < len(self.buf) else None

    def chunks(self, reader, overlap=0):
        yield self.base, self.base, self.buf, len(self.buf), len(self.buf)


def test_the_camera_block_is_found_by_its_names_and_read_as_eye_and_direction():
    """gGalacticScale alone is not trusted: the two axis names must sit where the game keeps them. The eye is
    the stored value x 100 (region units); the direction is perpendicular to the screen axes."""
    game = FakeGame()
    camera = lock(DS_POS, (1.0, -0.2, 0.5))
    game.look(camera)
    got = positions.CameraReader(chunker=game.chunks).read(game, 0.0)
    assert all(abs(a - b) < 1e-3 for a, b in zip(got["eye"], camera["eye"]))
    assert all(abs(a - b) < 1e-5 for a, b in zip(got["forward"], camera["forward"]))
    blank = FakeGame(names=False)
    blank.look(camera)
    assert positions.CameraReader(chunker=blank.chunks).read(blank, 0.0) is None
    assert positions.parse_value(struct.pack("<3f", 0, 0, 0)) is None and positions.parse_value(None) is None
    assert positions.parse_value(struct.pack("<3f", float("nan"), 1, 1)) is None


def test_two_locks_of_a_star_meet_at_it_and_distances_follow_the_maps_rule():
    """Lines of sight of one star from two directions meet at the star (miss 0); parallel lines do not; the
    map's distance is floor(|a - b| x 400): Delta Sol to Kayana XIV read 157 LJ on 2026-10-05 (157.6)."""
    a, b = lock(DS_POS, (1, 0, 0)), lock(DS_POS, (0, 0.3, 1))
    point, miss, angle = positions.closest_point(a["eye"], a["forward"], b["eye"], b["forward"])
    assert math.dist(point, DS_POS) < 1e-4 and miss < 1e-4 and angle > 80
    assert positions.closest_point(a["eye"], a["forward"], a["eye"], a["forward"]) is None
    assert positions.map_distance_ly(DS_POS, KAYANA_POS) == 157


def feed_lock(fixer, camera, samples=3):
    out = []
    for _ in range(samples):
        out += fixer.feed(camera)
    return out


def test_settled_views_that_meet_become_a_star_fix_and_more_locks_refine_it():
    """A settled view (the same eye twice) is one line of sight; a second lock of the same star from another
    direction makes a fix at the star, a third confirms it. Views that do not meet, nearly parallel ones and a
    moving camera make no fix."""
    clock = iter(range(1000, 2000, 10))
    fixer = positions.StarFixer(clock=lambda: next(clock))
    assert feed_lock(fixer, lock(DS_POS, (1, 0, 0))) == []
    assert feed_lock(fixer, lock(KAYANA_POS, (0, 0, 1))) == []          # another star: the lines miss
    made = feed_lock(fixer, lock(DS_POS, (0, 1, 1)))
    assert len(made) == 1 and made[0]["id"] == 1 and made[0]["rays"] == 2 and made[0]["system"] is None
    assert math.dist(made[0]["position"], DS_POS) * 400 < 0.01
    feed_lock(fixer, lock(DS_POS, (-1, 0.2, 0.3)))
    assert len(fixer.fixes) == 1 and fixer.fixes[0]["rays"] >= 3
    feed_lock(fixer, lock(KAYANA_POS, (0.02, 0, 1)))                   # 1 degree off the first Kayana line
    assert len(fixer.fixes) == 1
    moving = positions.StarFixer(clock=lambda: 0)
    for i in range(5):
        assert moving.feed(lock(DS_POS, (1, 0.1 * i, 0))) == [] and moving.feed(None) == []


def test_fixes_are_kept_named_by_the_user_and_old_eye_positions_are_discarded(tmp_path):
    """The history keeps star fixes; only named ones give positions. Positions recorded before 0.10.0 were the
    map camera's eye, not stars: they move to positions_discarded and are never used again."""
    path = tmp_path / "h.json"
    path.write_text(json.dumps({"version": 2, "planets": {}, "positions": {"620002925e80": [-383.5, 2.3, -1754.4]}}))
    history = PlanetHistory(path)
    assert history.positions == {} and history.positions_discarded == {"620002925e80": [-383.5, 2.3, -1754.4]}
    history.star_fixes.append({"id": 1, "position": list(DS_POS), "rays": 2, "miss_ly": 0.1, "system": f"{DELTA_SOL:x}"})
    history.star_fixes.append({"id": 2, "position": list(KAYANA_POS), "rays": 2, "miss_ly": 0.0, "system": None})
    history.star_fixes.append({"id": "bad"})
    history.save()
    again = PlanetHistory(path)
    assert [f["id"] for f in again.star_fixes] == [1, 2] and again.positions == {DELTA_SOL: DS_POS}
    assert again.positions_discarded == {"620002925e80": [-383.5, 2.3, -1754.4]}


def test_exact_distances_use_the_maps_rule_and_say_prototype():
    """Two systems with named fixes are measured as the map does (decimals cut) and shown as exact prototype
    values; without both, distances stay between regions ('same region')."""
    galaxy.set_positions({DELTA_SOL: DS_POS, KAYANA: KAYANA_POS})
    try:
        ly = galaxy.distance_ly(DELTA_SOL, KAYANA)
        assert ly == 157 and isinstance(ly, galaxy.ExactLy)
        assert galaxy.distance_text(ly) == "157 ly (exact, prototype)"
        galaxy.set_positions({DELTA_SOL: DS_POS})
        assert galaxy.distance_text(galaxy.distance_ly(DELTA_SOL, KAYANA)) == "same region (< 400 ly)"
    finally:
        galaxy.set_positions({})


class Live:
    status, error, current, current_source, current_system = "ok", None, None, "planets", DELTA_SOL


class Texts:
    trading, trading_source = None, "built-in"

    def text(self, key):
        return None


def test_the_star_positions_tab_explains_lists_fixes_and_offers_names(tmp_path):
    """Systems -> Star positions (prototype): the how-to says prototype, each fix shows its system and its
    distance from you once your own system's fix is named; the form lists your system first and can forget."""
    history = PlanetHistory(tmp_path / "h.json")
    history.system_names = {DELTA_SOL: "Ziverkess", KAYANA: "Agestr"}
    history.star_fixes += [{"id": 1, "position": list(DS_POS), "rays": 4, "miss_ly": 0.2, "system": None},
                           {"id": 2, "position": list(KAYANA_POS), "rays": 2, "miss_ly": 0.0, "system": None}]
    ctx = planets_view.Context(Live(), history, {}, Texts(), None)
    notice, table, form = planets_view.star_fix_sections(ctx)
    assert "PROTOTYPE" in notice["text"] and table["id"] == planets_view.STAR_FIX_ID
    assert table["rows"][1][1:3] == ["not named yet", "name the fix of the system you are in first"]
    systems = form["fields"][1]["options"]
    assert systems[0]["label"].startswith("Ziverkess") and systems[0]["label"].endswith("you are here")
    assert systems[-1]["value"] == positions.FORGET and form["fields"][0]["value"] == "2"
    history.star_fixes[0]["system"] = f"{DELTA_SOL:x}"
    galaxy.set_positions(history.positions)
    try:
        rows = planets_view.star_fix_sections(ctx)[1]["rows"]
        assert rows[0][2] == "you are here" and rows[1][2] == "157 ly (prototype)"
    finally:
        galaxy.set_positions({})


def test_naming_a_fix_checks_its_input_keeps_one_fix_per_system_and_can_forget(tmp_path, monkeypatch):
    """The naming action treats form values as untrusted: unknown fix or system answers ok False; naming
    replaces an older fix of that system; 'forget' drops the fix; exact distances follow at once."""
    from nms_connector import create_plugin
    from test_connector import FakeCtx
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.history.star_fixes += [{"id": 1, "position": list(DS_POS), "rays": 2, "miss_ly": 0.1, "system": f"{DELTA_SOL:x}"},
                                  {"id": 2, "position": list(DS_POS), "rays": 3, "miss_ly": 0.0, "system": None}]
    try:
        assert plugin._name_fix({"fix": "x"})["ok"] is False
        assert plugin._name_fix({"fix": "9", "system": "620002925e80"})["ok"] is False
        assert plugin._name_fix({"fix": "2", "system": "not hex"})["ok"] is False
        assert plugin._name_fix({"fix": "2", "system": "620002925e80"})["ok"] is True
        assert [f["system"] for f in plugin.history.star_fixes] == [None, "620002925e80"]
        assert galaxy.exact(DELTA_SOL) == DS_POS
        assert plugin._name_fix({"fix": "1", "system": positions.FORGET})["ok"] is True
        assert [f["id"] for f in plugin.history.star_fixes] == [2]
    finally:
        galaxy.set_positions({})


def test_a_fix_is_the_best_intersection_of_its_lines_and_a_stray_line_is_dropped():
    """With three or more lines the fix is their least-squares intersection; a line of another star that still
    paired with one of them (misses > 0.5 LJ) is dropped instead of pulling the position (seen in a replay of
    real data, 2026-10-05: 1.4 LJ off before)."""
    lines = [[list(lock(DS_POS, d)["eye"]), list(lock(DS_POS, d)["forward"])] for d in ((1, 0, 0), (0, 1, 1), (-1, 0.2, 0.3))]
    point, miss, _ = positions.intersect(lines)
    assert math.dist(point, DS_POS) * 400 < 0.01 and miss * 400 < 0.01
    fixer = positions.StarFixer(clock=lambda: 1000)
    a, b = lock(DS_POS, (1, 0, 0)), lock(DS_POS, (0, 1, 1))
    stray = lock(tuple(c + 0.004 for c in DS_POS), (-1, 0.1, 0.2))         # 2.8 LJ off: another star's line
    fix = fixer._merge(DS_POS, (a, b), 1000)
    fix = fixer._merge(DS_POS, (stray, a), 1000)
    assert fix["rays"] == 2 and math.dist(fix["position"], DS_POS) * 400 < 0.01 and fix["miss_ly"] <= 0.5


def test_only_a_camera_still_for_two_seconds_counts_as_a_lock():
    """While the camera eases into a lock its eye changes every sample; a line of sight is taken only after
    SETTLED_SAMPLES equal samples (3 = 2 s). With 2, easing samples made 7 false fixes in a replay of real data."""
    fixer = positions.StarFixer(clock=lambda: 0)
    for step in range(5):
        fixer.feed(lock(DS_POS, (1, 0, 0), back=0.2 + 0.01 * step))
    assert fixer.rays == []
    feed_lock(fixer, lock(DS_POS, (1, 0, 0)), samples=positions.SETTLED_SAMPLES - 1)
    assert fixer.rays == []
    fixer.feed(lock(DS_POS, (1, 0, 0)))
    assert len(fixer.rays) == 1 and positions.SETTLED_SAMPLES == 3
