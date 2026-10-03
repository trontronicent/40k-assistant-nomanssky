"""Tests for the read-only memory reading, visit history and planet tables: no game process needed.

Process memory is faked by a reader over byte regions; planet records are built
in the real GcPlanetData layout, so validation and scanning run exactly as on
the game's memory.
"""

import struct

import pytest

from nms_connector import live as live_mod
from nms_connector import memory, planets_view
from nms_connector.history import PlanetHistory, visits_from_save
from nms_connector.live import LiveMemory

pytest.importorskip("numpy")

SUBSTANCES = {"YELLOW2", "TOXIC1", "CATALYST1", "DUSTY1", "WATER1", "COLD1", "CAVE1"}
SYSTEM_98 = 0x620002925E80          # Euclid, voxel (-384, 2, -1755), system 98
SYSTEM_115 = 0x730002925E80


def fs(value: str, size: int) -> bytes:
    raw = value.encode("utf-8")
    return raw + bytes(size - len(raw))


def planet_blob(name="Yaksh Primus", index=0, system=SYSTEM_98, ids=("YELLOW2", "TOXIC1", "CATALYST1"),
                weather="WEATHER_TOXIC_CLEAR3", hints_ptr=0, hints=0, biome=1, size=1) -> bytearray:
    """A GcPlanetData record (libMBIN layout) with the fields the reader uses."""
    b = bytearray(memory.PLANET_SIZE)
    common, uncommon, rare = ids
    b[memory.P_COMMON:memory.P_COMMON + 16] = fs(common, 16)
    b[memory.P_UNCOMMON:memory.P_UNCOMMON + 16] = fs(uncommon, 16)
    b[memory.P_RARE:memory.P_RARE + 16] = fs(rare, 16)
    struct.pack_into("<QI", b, memory.P_EXTRA_HINTS, hints_ptr, hints)
    struct.pack_into("<i", b, memory.P_INDEX, index)
    struct.pack_into("<Q", b, memory.P_PLANET_UA, system | (index + 1) << 52)
    struct.pack_into("<4i", b, memory.P_GENERATION + 0x138, biome, 0, 0, size)
    info = memory.P_INFO
    for i, key in enumerate(["SENTINEL_RARE4", "SENTINEL_RARE4", "SENTINEL_DEFAULT5", "SENTINEL_DEFAULT9"]):
        b[info + i * 0x80:info + i * 0x80 + 0x80] = fs(key, 0x80)
    for field, value in (("fauna", "RARITY_MID9"), ("flora", "RARITY_HIGH7"), ("description", "TOXIC3"),
                         ("type", "PLANETCLASS1"), ("resources", "RARITY_MID2"), ("weather", weather)):
        off = info + memory.INFO_FIELDS[field]
        b[off:off + 0x80] = fs(value, 0x80)
    b[memory.P_NAME:memory.P_NAME + 0x80] = fs(name, 0x80)
    return b


class FakeReader:
    """Process memory as {base: bytearray} regions (all treated as private read/write)."""

    def __init__(self, regions: dict[int, bytearray], pid=4242):
        self.mem, self.pid, self.closed = regions, pid, False

    def regions(self):
        for base in sorted(self.mem):
            yield base, len(self.mem[base])

    def read(self, address, size):
        for base, data in self.mem.items():
            if base <= address < base + len(data):
                return bytes(data[address - base:address - base + size])
        return None

    def close(self):
        self.closed = True


def player_state_region(current=(1, 98), start1=(1, 78), start2=(0, 139)) -> tuple[bytearray, bytes]:
    """Bytes holding GameStartAddress1/2 followed by UniverseAddress at the libMBIN distance."""
    def ua(planet, system):
        return {"RealityIndex": 0, "GalacticAddress": {"PlanetIndex": planet, "SolarSystemIndex": system,
                                                       "VoxelX": -384, "VoxelY": 2, "VoxelZ": -1755}}
    anchor = memory.ua_bytes(ua(*start1)) + memory.ua_bytes(ua(*start2))
    at = 0x40 + memory.UA_AFTER_GAME_START
    region = bytearray(max(0x200, at + 0x40))
    region[0x40:0x40 + len(anchor)] = anchor
    region[at:at + 24] = memory.ua_bytes(ua(*current))
    return region, anchor


# --------------------------------------------------------------------------- records


def test_planet_record_is_parsed_and_validated():
    """A real-layout record gives name, index, resources (common/uncommon/rare), biome and summary keys; a
    record whose PlanetUA planet nibble does not match its index, an unprintable name or a resource that is
    not a substance is rejected - nothing half-valid reaches the view."""
    planet = memory.parse_planet(bytes(planet_blob()), substances=SUBSTANCES)
    assert planet["name"] == "Yaksh Primus" and planet["index"] == 0 and planet["system"] == SYSTEM_98
    assert (planet["common"], planet["uncommon"], planet["rare"]) == ("YELLOW2", "TOXIC1", "CATALYST1")
    assert planet["biome"] == "Toxic" and planet["size"] == "Medium"
    assert planet["info"]["weather"] == "WEATHER_TOXIC_CLEAR3" and planet["info"]["sentinels"][2] == "SENTINEL_DEFAULT5"
    wrong_ua = planet_blob()
    struct.pack_into("<Q", wrong_ua, memory.P_PLANET_UA, SYSTEM_98 | 5 << 52)
    assert memory.parse_planet(bytes(wrong_ua)) is None
    bad_name = planet_blob()
    bad_name[memory.P_NAME:memory.P_NAME + 3] = b"\x01\x02\x03"
    assert memory.parse_planet(bytes(bad_name)) is None
    assert memory.parse_planet(bytes(planet_blob(ids=("YELLOW2", "TOXIC1", "LASER"))), substances=SUBSTANCES) is None


def test_addresses_pack_like_the_game():
    """Universe addresses pack into the game's u64 layout (as in the save's VisitedSystems), the planet nibble
    is cleared for the system key, and out-of-range addresses read from memory are refused."""
    ua = {"RealityIndex": 0, "GalacticAddress": {"PlanetIndex": 1, "SolarSystemIndex": 98, "VoxelX": -384,
                                                 "VoxelY": 2, "VoxelZ": -1755}}
    assert memory.pack_address(ua) == 0x10620002925E80 and memory.system_key(0x10620002925E80) == SYSTEM_98
    assert memory.ua_from_bytes(memory.ua_bytes(ua)) == ua
    assert memory.ua_from_bytes(struct.pack("<6i", 1, 98, 9999, 2, -1755, 0)) is None


# --------------------------------------------------------------------------- scanning


def test_scan_finds_planets_hints_and_the_player_state(monkeypatch):
    """Planets anywhere in private memory are found - including one that crosses a chunk boundary - with
    their extra resource hints read through the record's list pointer; the player-state copy whose system
    has planets is chosen over a stale copy."""
    monkeypatch.setattr(memory, "CHUNK", 0x8000)
    hints = bytearray(0x40)
    hints[0:16], hints[0x20:0x30] = fs("PLANT_TOXIC", 16), fs("PLANT_DUST", 16)
    region = bytearray(0x30000)
    first = planet_blob(hints_ptr=0x900000, hints=2)
    region[0x1000:0x1000 + len(first)] = first
    second = planet_blob("Ezaw 36/M3", 1, ids=("YELLOW2", "DUSTY1", "WATER1"))
    at = 0x8000 - memory.P_COMMON - 0x20          # its substance rows end exactly at the chunk boundary
    at -= at % 16
    region[at:at + len(second)] = second
    stale = planet_blob("Itwi A1", 5, system=SYSTEM_115, ids=("YELLOW2", "DUSTY1", "CATALYST1"))
    region[0x20000:0x20000 + len(stale)] = stale
    old_state, anchor = player_state_region(current=(0, 7))
    state, same_anchor = player_state_region(current=(1, 98))
    assert anchor == same_anchor
    reader = FakeReader({0x100000: region, 0x900000: hints, 0x500000: old_state, 0x600000: state})
    result = memory.scan(reader, SUBSTANCES, anchor)
    names = [(p["name"], p["system"]) for p in result.planets]
    assert names == [("Yaksh Primus", SYSTEM_98), ("Ezaw 36/M3", SYSTEM_98), ("Itwi A1", SYSTEM_115)]
    assert result.planets[0]["extra"] == ["PLANT_TOXIC", "PLANT_DUST"]
    assert len(result.player_states) == 2
    address, ua = result.best_player_state(reader)
    assert address == 0x600000 + 0x40 and ua["GalacticAddress"]["SolarSystemIndex"] == 98


# --------------------------------------------------------------------------- history


def save_with_visits() -> dict:
    return {"BaseContext": {"PlayerStateData": {"VisitedSystems": [0x10620002925E80, SYSTEM_115]}},
            "DiscoveryManagerData": {"DiscoveryData-v1": {"Store": {"Record": [
                {"DD": {"UA": SYSTEM_98, "DT": "SolarSystem"}, "DM": {"CN": "Delta Sol"},
                 "OWS": {"USN": "Charlie Papa", "TS": 1700000000}},
                {"DD": {"UA": 0x10620002925E80, "DT": "Planet"}, "DM": {"CN": "Corrodia"}, "OWS": {"USN": "Charlie Papa"}},
                {"DD": {"UA": "0x10620002925E80", "DT": "Flora"}, "DM": {}, "OWS": {}},
                {"DD": {"UA": 0x10620002925E80, "DT": "Animal"}, "DM": {}, "OWS": {}},
                {"DD": {"UA": 0x10620002925E80, "DT": "Animal"}, "DM": {}, "OWS": {}},
            ]}}}}


def test_visits_from_save_collect_systems_names_and_discoveries():
    """VisitedSystems and discovery records give one entry per system (planet nibble cleared) with uploaded
    system and planet names, who named them, and flora/fauna counts per planet (index 0-based)."""
    visits = visits_from_save(save_with_visits())
    assert set(visits) == {SYSTEM_98, SYSTEM_115}
    delta = visits[SYSTEM_98]
    assert delta["visited"] and delta["name"] == "Delta Sol" and delta["named_by"] == "Charlie Papa"
    assert delta["planets"][0] == {"name": "Corrodia", "named_by": "Charlie Papa", "flora": 1, "fauna": 2}
    assert visits[SYSTEM_115]["name"] is None and visits[SYSTEM_115]["visited"]


def test_planet_history_keeps_first_seen_and_counts_changes(tmp_path):
    """Recording the same planet again changes only last_seen (not counted as a change); new data is;
    the history survives a reload."""
    history = PlanetHistory(tmp_path / "planet_history.json")
    planet = memory.parse_planet(bytes(planet_blob()))
    assert history.record([planet], "2026-10-03T10:00:00") == 1
    assert history.record([planet], "2026-10-03T11:00:00") == 0
    history.save()
    again = PlanetHistory(tmp_path / "planet_history.json")
    stored = again.planets[planet["ua"]]
    assert stored["first_seen"] == "2026-10-03T10:00:00" and stored["last_seen"] == "2026-10-03T11:00:00"
    assert list(again.systems()) == [SYSTEM_98]


# --------------------------------------------------------------------------- pacing


class FakeScan:
    def __init__(self, planets, states):
        self.calls, self.planets, self.states = 0, planets, states

    def __call__(self, reader, substances, anchor):
        self.calls += 1
        return memory.ScanResult(list(self.planets), list(self.states) if anchor else [], 1 << 30, 0.5)


def test_live_memory_scans_only_when_needed(tmp_path):
    """Not running -> nothing read; the first tick with the save's anchor scans and finds the current system;
    later ticks only re-read the address; moving to another system scans at once and once more after the
    follow-up delay; a full rescan also happens after RESCAN_S."""
    region, anchor = player_state_region(current=(1, 98))
    reader = FakeReader({0x600000: region})
    pid = {"value": None}
    scan = FakeScan([memory.parse_planet(bytes(planet_blob()))], [0x600000 + 0x40])
    live = LiveMemory(PlanetHistory(tmp_path / "h.json"), opener=lambda p: reader, pid_finder=lambda: pid["value"],
                      scanner=scan)
    assert live.tick(anchor, None, 0) == 0 and live.status == "not-running" and scan.calls == 0
    pid["value"] = 4242
    assert live.tick(anchor, None, 10) == 1 and scan.calls == 1 and live.current_system == SYSTEM_98
    live.tick(anchor, None, 15)
    assert scan.calls == 1 and live.status == "ok"
    at = 0x40 + memory.UA_AFTER_GAME_START
    region[at:at + 24] = memory.ua_bytes({"RealityIndex": 0, "GalacticAddress": {
        "PlanetIndex": 0, "SolarSystemIndex": 115, "VoxelX": -384, "VoxelY": 2, "VoxelZ": -1755}})
    live.tick(anchor, None, 20)
    assert scan.calls == 2 and live.current_system == SYSTEM_115
    live.tick(anchor, None, 20 + live_mod.FOLLOW_UP_S - 1)
    assert scan.calls == 2
    live.tick(anchor, None, 20 + live_mod.FOLLOW_UP_S)
    assert scan.calls == 3
    live.tick(anchor, None, 20 + live_mod.FOLLOW_UP_S + live_mod.RESCAN_S)
    assert scan.calls == 4
    pid["value"] = None
    live.tick(anchor, None, 9999)
    assert reader.closed and live.current_system is None


def test_live_memory_reports_access_problems(tmp_path):
    """An access error (e.g. the game runs as administrator) becomes a readable status, not an exception."""
    def refuse(pid):
        raise memory.MemoryUnavailable("cannot open the game process (Windows error 5)")
    live = LiveMemory(PlanetHistory(tmp_path / "h.json"), opener=refuse, pid_finder=lambda: 7, scanner=FakeScan([], []))
    assert live.tick(b"x", None, 0) == 0
    assert live.status == "error" and "error 5" in live.error


# --------------------------------------------------------------------------- tables


class FakeGameData:
    names = {"YELLOW2": ("Copper", "Kupfer"), "TOXIC1": ("Ammonia", "Ammoniak"), "CATALYST1": ("Sodium", "Natrium"),
             "PLANT_TOXIC": ("Fungal Mould", "Pilzschimmel")}
    texts = {"TOXIC3": ("Noxious %PLANETCLASS%", "Ungesunder %PLANETCLASS%"), "PLANETCLASS1": ("Planet", "Planet"),
             "WEATHER_TOXIC_CLEAR3": ("Poison Rain", "Giftregen"), "SENTINEL_DEFAULT5": ("Require Obedience", "Erwarten Gehorsam"),
             "RARITY_HIGH7": ("Bountiful", "Reichhaltig"), "RARITY_MID9": ("Fair", "Fair")}

    def lookup(self, item_id):
        en, local = self.names.get(item_id, (None, None))
        return {"en": en, "local": local} if en else None

    def icon_name(self, item_id):
        return "substance.yellow.2.png" if item_id == "YELLOW2" else None

    def text(self, key):
        en, local = self.texts.get(key, (None, None))
        return {"en": en, "local": local} if en else None


def test_tables_show_the_current_system_and_every_visited_system(tmp_path):
    """The current system's planets show the uploaded name with the generated one, translated type, weather,
    sentinels for the save's combat timer, resources with icons; the visited-systems table lists the current
    system first, then systems with resources, then save-only systems; recorded planets get their own table."""
    history = PlanetHistory(tmp_path / "h.json")
    planet = memory.parse_planet(bytes(planet_blob(hints_ptr=0)))
    planet["extra"] = ["PLANT_TOXIC"]
    history.record([planet], "2026-10-03T23:00:00")

    class Live:
        status, error = "ok", None
        current_system = SYSTEM_98
        current = {"RealityIndex": 0, "GalacticAddress": {"PlanetIndex": 1, "SolarSystemIndex": 98,
                                                          "VoxelX": -384, "VoxelY": 2, "VoxelZ": -1755}}

    out = planets_view.sections(Live(), history, visits_from_save(save_with_visits()), FakeGameData(), "Normal")
    current = out[0]
    assert current["title"] == "Current system: Delta Sol (live from the game)"
    row = current["rows"][0]
    assert row[:3] == ["Corrodia (Yaksh Primus)", "Noxious Planet (Ungesunder Planet)", "Poison Rain (Giftregen)"]
    assert row[3] == {"text": "Copper (Kupfer)", "icon": "substance.yellow.2.png"} and row[5] == "Sodium (Natrium)"
    assert row[6] == "Fungal Mould" and row[9] == "Require Obedience (Erwarten Gehorsam)"
    where = {i["label"]: i["value"] for i in out[1]["items"]}
    assert where == {"System": "Delta Sol", "Portal address": "006202925E80", "Galaxy": "Euclid",
                     "Planet": "Corrodia (Yaksh Primus)"}
    systems = out[2]
    assert systems["title"] == "Visited systems (2)" and systems["rows"][0][0] == "Delta Sol" and systems["rows"][0][7] == "yes"
    assert systems["rows"][1][0] == "System 007302925E80" and systems["rows"][1][3] is None
    assert out[3]["title"] == "Visited planets with resources (1)" and out[3]["rows"][0][0] == "Delta Sol"


def test_tables_explain_when_the_game_is_not_running(tmp_path):
    """Without the game the view says how live data appears, and still lists the save's visited systems."""
    class Live:
        status, error, current_system, current = "not-running", None, None, None
    out = planets_view.sections(Live(), PlanetHistory(tmp_path / "h.json"), visits_from_save(save_with_visits()),
                                FakeGameData(), None)
    assert out[0]["type"] == "notice" and "Start No Man's Sky" in out[0]["text"]
    assert out[1]["title"] == "Visited systems (2)" and "every system you visit" in out[2]["empty"]
