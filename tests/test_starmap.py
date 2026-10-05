"""Tests for the game's generation rules (procgen) and the galaxy map's star records (starmap)."""

import struct

from nms_connector import memory, procgen, starmap

YIBRAZH = 0x0170002925E80
DELTA_SOL = 0x0620002925E80
ULEBSK = 0x0DA0002925E80


def test_planet_seeds_are_the_games():
    """The seeds derived from an address are the game's GenerationData.Seed values, in planet-index order (read
    from memory 2026-10-05: Yibrazh's six and Delta Sol's five planets)."""
    assert [f"{s:016x}" for s in procgen.planet_seeds(YIBRAZH)] == [
        "bda5a0b2c929a9f8", "7afbae2723399049", "1596252e9134303b", "94b2871f30f8ce47", "9f452fdf5d75c2d3",
        "883c0ccf433cbc8c"]
    assert f"{procgen.planet_seeds(DELTA_SOL)[0]:016x}" == "2e532789e2681556"


def test_predicted_attributes_match_what_the_game_showed():
    """Economy, wealth, conflict, race and star of systems read in the game (visits, 2026-10-04/05) are predicted
    exactly; a pirate system shows conflict Pirate, as in the game."""
    a = procgen.system_attributes(DELTA_SOL)
    assert (a["economy"], a["wealth"], a["conflict"], a["race"], a["star"]) == ("Mining", "Average", "Low", "Korvax", "Yellow")
    u = starmap.predicted(ULEBSK)
    assert (u["economy"], u["wealth"], u["conflict"], u["race"]) == ("Manufacturing", "Average", "High", "Korvax")
    assert u["predicted"] is True
    pirate = starmap.predicted(0x0790002925E80)
    assert pirate["pirate"] and pirate["conflict"] == "Pirate" and pirate["economy"] == "HighTech"
    assert procgen.portal_code(YIBRAZH) == (0x001702925E80, 0)


def test_the_neighbourhood_covers_the_regions_around_you():
    """27 regions (yours and the 26 around it), every system index up to the purple ones (0x42F)."""
    keys = starmap.neighbourhood(YIBRAZH, radius=1)
    assert len(keys) == 27 * procgen.MAX_SYSTEM_INDEX and DELTA_SOL in keys
    assert (0x0010002925E81 in keys) and (0x0010002926E80 in keys)      # x+1, z+1


def record(seeds, trading=3, wealth=1, conflict=2, planets=5, race=2, star=0):
    """A GcGalaxyStarAttributesData record with these planet seeds and values."""
    blob = bytearray(memory.STAR_SIZE)
    for k, seed in enumerate(seeds):
        struct.pack_into("<QB", blob, memory.STAR_PLANET_SEEDS + k * 0x10, seed, 1)
    struct.pack_into("<2i", blob, memory.STAR_TRADING, trading, wealth)
    struct.pack_into("<7i", blob, memory.STAR_TAIL, 0, conflict, planets, 0, 0, race, star)
    return bytes(blob)


class Memory:
    def __init__(self, blobs):
        self.buf = bytearray(0x10)
        self.base = 0x2E961390000
        for b in blobs:
            self.buf += b + bytes((-len(b)) % 16)
        self.buf += bytes(0x40)

    def read(self, address, size):
        off = address - self.base
        return bytes(self.buf[off:off + size]) if 0 <= off < len(self.buf) else None

    def chunks(self, reader, overlap=0):
        yield self.base, self.base, self.buf, len(self.buf), len(self.buf)


def test_star_records_in_memory_are_traced_back_to_their_systems():
    """A record whose first two planet seeds are a listed system's is that system's (Ulebsk: Manufacturing,
    Average, High, Korvax - as read on the visit); a record with only the first seed right, or values out of
    range, is not taken."""
    ulebsk = procgen.planet_seeds(ULEBSK)
    delta = procgen.planet_seeds(DELTA_SOL)
    mem = Memory([record(ulebsk), record([delta[0], 12345]), record(procgen.planet_seeds(YIBRAZH), trading=99)])
    table = starmap.seed_table([ULEBSK, DELTA_SOL, YIBRAZH])
    found = starmap.find_records(mem, table, mem.chunks)
    assert set(found) == {ULEBSK}
    assert (found[ULEBSK]["economy"], found[ULEBSK]["wealth"], found[ULEBSK]["conflict"], found[ULEBSK]["race"]) == \
        ("Manufacturing", "Average", "High", "Korvax")
    assert starmap.find_records(mem, {}, mem.chunks) == {}


def test_the_reader_scans_at_most_every_few_minutes_and_caches_the_table_per_region(monkeypatch):
    """A scan builds the region's seed table once; another system of the same region reuses it."""
    built = []
    monkeypatch.setattr(starmap, "neighbourhood", lambda c, radius=1: [ULEBSK])
    real = starmap.seed_table
    monkeypatch.setattr(starmap, "seed_table", lambda keys: built.append(1) or real(keys))
    mem = Memory([record(procgen.planet_seeds(ULEBSK))])
    now = [1000.0]
    reader = starmap.StarmapReader(chunker=mem.chunks, clock=lambda: now[0])
    assert reader.due(now[0]) and set(reader.scan(mem, YIBRAZH)) == {ULEBSK}
    assert not reader.due(now[0] + 10) and reader.due(now[0] + starmap.StarmapReader.SCAN_EVERY_S)
    reader.scan(mem, DELTA_SOL)                      # same region
    assert len(built) == 1 and reader.last_found == 1
