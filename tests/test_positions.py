"""Tests for exact system positions: reading gGalacticScale, when a reading may be recorded, exact distances."""

import struct

from nms_connector import galaxy, positions
from nms_connector.history import PlanetHistory

YIBRAZH = 0x0170002925E80                 # region (-384, 2, -1755), system 0x017 (2026-10-05)
VALUE = (-3.837331, 0.020779, -17.541409)  # what the game held there: the position / 100


class FakeGame:
    """Memory with the parameter name at `at` and its value 0x20 bytes later (read-only reader + chunker)."""

    def __init__(self, value=VALUE, at=0x1000):
        self.base, self.at = 0x2E9591F0000, at
        self.buf = bytearray(0x4000)
        self.buf[at:at + 16] = positions.GALACTIC_NAME
        self.set(value)
        self.searches = 0

    def set(self, value):
        struct.pack_into("<3f", self.buf, self.at + positions.GALACTIC_VALUE_AT, *value)

    def read(self, address, size):
        off = address - self.base
        return bytes(self.buf[off:off + size]) if 0 <= off < len(self.buf) else None

    def chunks(self, reader, overlap=0):
        self.searches += 1
        yield self.base, self.base, self.buf, len(self.buf), len(self.buf)


def test_the_value_is_read_as_a_voxel_position_and_checked_against_the_region():
    """The parameter holds the position / 100: Yibrazh's reads (-383.733, 2.078, -1754.141), inside its region
    (-384, 2, -1755); zeros, huge or non-finite values are not positions."""
    pos = positions.parse_value(struct.pack("<3f", *VALUE))
    assert pos == (-383.7331, 2.0779, -1754.1409)
    assert positions.inside_region(pos, galaxy.region(YIBRAZH))
    assert not positions.inside_region(pos, (-383, 2, -1755))
    assert positions.parse_value(struct.pack("<3f", 0, 0, 0)) is None
    assert positions.parse_value(struct.pack("<3f", float("nan"), 1, 1)) is None
    assert positions.parse_value(struct.pack("<3f", 1e9, 1, 1)) is None and positions.parse_value(None) is None


def test_a_reading_is_offered_only_once_settled_in_the_system_and_inside_its_region():
    """The parameter is found by its name once; a reading counts for the current system only after SETTLE_S in
    it (the last system's value may linger during a warp) and only inside its region; a moved value is found
    again, at most every SEARCH_EVERY_S."""
    game = FakeGame()
    tracker = positions.PositionTracker(chunker=game.chunks)
    region = galaxy.region(YIBRAZH)
    assert tracker.tick(game, YIBRAZH, region, 1000) is None and tracker.last == (-383.7331, 2.0779, -1754.1409)
    assert tracker.tick(game, YIBRAZH, region, 1000 + positions.SETTLE_S) == (YIBRAZH, (-383.7331, 2.0779, -1754.1409))
    other = 0x0180002925E81                                 # another system in another region
    assert tracker.tick(game, other, galaxy.region(other), 1100) is None
    assert tracker.tick(game, other, galaxy.region(other), 1200) is None          # value outside its region
    assert game.searches == 1
    assert tracker.tick(game, None, None, 1300) is None


def test_a_reading_another_system_already_has_is_stale_and_refused():
    """Two systems of one region pass the region check with the same lingering value: the second is refused."""
    known = {YIBRAZH: (-383.7331, 2.0779, -1754.1409)}
    assert not positions.accept(known, 0x0180002925E80, (-383.7331, 2.0779, -1754.1409))
    assert positions.accept(known, 0x0180002925E80, (-383.2, 2.5, -1754.9))
    assert positions.accept(known, YIBRAZH, (-383.7331, 2.0779, -1754.1409))


def test_distances_and_map_use_exact_positions_where_both_are_known(tmp_path):
    """Two systems of one region were 'same region (< 400 ly)'; with exact positions they are measured (here
    0.5 voxel = 200 ly); with one position missing the region distance stays. Positions persist in the history."""
    other = 0x0180002925E80
    try:
        galaxy.set_positions({YIBRAZH: (-383.5, 2.0, -1754.5), other: (-383.0, 2.0, -1754.5)})
        assert galaxy.distance_ly(YIBRAZH, other) == 200
        assert galaxy.distance_text(galaxy.distance_ly(YIBRAZH, other)) == "~200 ly"
        assert galaxy.map_position(YIBRAZH) == (-383.5, 2.0, -1754.5)
        third = 0x0190002925E80
        assert galaxy.distance_ly(YIBRAZH, third) == 0                       # same region, one position missing
        history = PlanetHistory(tmp_path / "h.json")
        history.positions[YIBRAZH] = (-383.5, 2.0, -1754.5)
        history.save()
        assert PlanetHistory(tmp_path / "h.json").positions == {YIBRAZH: (-383.5, 2.0, -1754.5)}
    finally:
        galaxy.set_positions({})
