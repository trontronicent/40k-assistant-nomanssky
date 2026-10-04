"""Tests for the read-only memory reading, visit history and planet tables: no game process needed.

Process memory is faked by a reader over byte regions; planet records are built
in the real GcPlanetData layout, so validation and scanning run exactly as on
the game's memory.
"""

import json
import struct
import zlib

import pytest

from nms_connector import live as live_mod
from nms_connector import memory, planets_view
from nms_connector.history import PlanetHistory, planet_id, visits_from_save
from nms_connector.live import LiveMemory

pytest.importorskip("numpy")

SUBSTANCES = {"YELLOW2", "TOXIC1", "CATALYST1", "DUSTY1", "WATER1", "COLD1", "CAVE1"}
SYSTEM_98 = 0x620002925E80          # Euclid, voxel (-384, 2, -1755), system 98
SYSTEM_115 = 0x730002925E80


def fs(value: str, size: int) -> bytes:
    raw = value.encode("utf-8")
    return raw + bytes(size - len(raw))


def planet_blob(name="Yaksh Primus", index=0, system=SYSTEM_98, ids=("YELLOW2", "TOXIC1", "CATALYST1"),
                weather="WEATHER_TOXIC_CLEAR3", hints_ptr=0, hints=0, biome=1, size=1, seed=None) -> bytearray:
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
    # Each planet has its own generation seed; by default derived from the name so different planets differ.
    struct.pack_into("<Q?", b, memory.P_SEED, seed if seed is not None else (zlib.crc32(name.encode()) | 1) << 8, True)
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
    stored = again.planets[planet_id(planet)]
    assert stored["first_seen"] == "2026-10-03T10:00:00" and stored["last_seen"] == "2026-10-03T11:00:00"
    assert list(again.systems()) == [SYSTEM_98]


def test_a_reused_slot_with_a_stale_address_never_replaces_the_previous_system(tmp_path):
    """Bug 2026-10-03: after a warp the game reused the planet slots and the records kept the old system's
    addresses, so every planet of the old system was overwritten by one of the new system. Planets are now
    identified by address and name: the old system keeps its planets, and the new ones (another planet
    already owns their address) are filed under the system you are in. The scan log says so."""
    history = PlanetHistory(tmp_path / "planet_history.json")
    a = [memory.parse_planet(bytes(planet_blob(n, i))) for i, n in enumerate(["A-one", "A-two"])]
    history.record(a, "2026-10-03T10:00:00", SYSTEM_98)
    b = [memory.parse_planet(bytes(planet_blob(n, i))) for i, n in enumerate(["B-one", "B-two"])]   # stale: system 98
    assert history.record(b, "2026-10-03T11:00:00", SYSTEM_115) == 2
    history.record(b + [a[0]], "2026-10-03T11:05:00", SYSTEM_115)   # again, plus a genuine leftover of A
    history.save()
    systems = {k: [p["name"] for p in v] for k, v in PlanetHistory(tmp_path / "planet_history.json").systems().items()}
    assert systems == {SYSTEM_98: ["A-one", "A-two"], SYSTEM_115: ["B-one", "B-two"]}
    assert len(history.planets) == 4
    first, second, third = history.scans
    assert (first["new"], second["new"], second["moved"], third["new"], third["changed"]) == (2, 2, 2, 0, 0)
    assert second["systems"] == {f"{SYSTEM_115:x}": ["B-one", "B-two"]}


def test_a_planet_first_filed_by_a_stale_address_is_moved_once_confirmed(tmp_path):
    """Seen first (from another system) with nothing to contradict its stale address, a planet is filed
    there unconfirmed; read again while you are in its real system, that copy replaces the wrong one."""
    history = PlanetHistory(tmp_path / "h.json")
    ghost = memory.parse_planet(bytes(planet_blob("B-one", 0)))                       # says system 98
    history.record([ghost], "2026-10-03T10:00:00", SYSTEM_115)
    assert [p["confirmed"] for p in history.planets.values()] == [False]
    real = memory.parse_planet(bytes(planet_blob("B-one", 0, system=SYSTEM_115)))
    history.record([real], "2026-10-03T10:01:00", SYSTEM_115)
    assert {k: [p["name"] for p in v] for k, v in history.systems().items()} == {SYSTEM_115: ["B-one"]}
    assert all(p["confirmed"] for p in history.planets.values())


def test_scan_keeps_two_planets_that_share_an_address():
    """A stale slot and the live record with the same address but different names are both kept."""
    region = bytearray(0x20000)
    for at, name in ((0x1000, "A-one"), (0x9000, "B-one")):
        blob = planet_blob(name, 0)
        region[at:at + len(blob)] = blob
    result = memory.scan(FakeReader({0x100000: region}), SUBSTANCES, None)
    assert sorted(p["name"] for p in result.planets) == ["A-one", "B-one"]


def test_history_migrates_version_1_and_falls_back_to_the_backup(tmp_path):
    """A 0.3.0 file (keyed by address) loads into the new ids; each save keeps the previous file as .bak,
    which is read when the main file is damaged."""
    planet = memory.parse_planet(bytes(planet_blob()))
    old = {k: v for k, v in planet.items() if k != "ua"}
    path = tmp_path / "planet_history.json"
    path.write_text(json.dumps({"version": 1, "planets": {str(planet["ua"]): old}}), encoding="utf-8")
    history = PlanetHistory(path)
    assert list(history.planets) == [planet_id(planet)] and history.planets[planet_id(planet)]["ua"] == planet["ua"]
    history.save()
    history.record([memory.parse_planet(bytes(planet_blob("Other", 1)))], "2026-10-03T12:00:00", SYSTEM_98)
    history.save()
    path.write_text("{ broken", encoding="utf-8")
    assert list(PlanetHistory(path).planets) == [planet_id(planet)]     # the backup: the state before the last save


def test_live_memory_follows_the_player_state_copy_that_moves(tmp_path):
    """With two player-state copies the scan's pick may be a frozen one; the copy whose address changes
    when you travel is the live one and is followed from then on."""
    frozen, anchor = player_state_region(current=(1, 98))
    moving, _ = player_state_region(current=(1, 98))
    reader = FakeReader({0x500000: frozen, 0x600000: moving})
    scan = FakeScan([], [0x500000 + 0x40, 0x600000 + 0x40])
    live = LiveMemory(PlanetHistory(tmp_path / "h.json"), opener=lambda p: reader, pid_finder=lambda: 4242, scanner=scan)
    live.tick(anchor, None, 0)
    assert live.player_state == 0x500000 + 0x40 and live.current_system == SYSTEM_98
    at = 0x40 + memory.UA_AFTER_GAME_START
    moving[at:at + 24] = memory.ua_bytes({"RealityIndex": 0, "GalacticAddress": {
        "PlanetIndex": 0, "SolarSystemIndex": 115, "VoxelX": -384, "VoxelY": 2, "VoxelZ": -1755}})
    live.tick(anchor, None, 10)
    assert live.player_state == 0x600000 + 0x40 and live.current_system == SYSTEM_115 and scan.calls == 2


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
             "PLANT_TOXIC": ("Fungal Mould", "Pilzschimmel"), "GAS3": ("Nitrogen", "Stickstoff")}
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


class LiveIn98:
    status, error = "ok", None
    current_system = SYSTEM_98
    current = {"RealityIndex": 0, "GalacticAddress": {"PlanetIndex": 1, "SolarSystemIndex": 98,
                                                      "VoxelX": -384, "VoxelY": 2, "VoxelZ": -1755}}


def recorded_toxic_planet(tmp_path) -> PlanetHistory:
    history = PlanetHistory(tmp_path / "h.json")
    planet = memory.parse_planet(bytes(planet_blob(hints_ptr=0)))
    planet["extra"] = ["PLANT_TOXIC"]
    history.record([planet], "2026-10-03T23:00:00")
    return history


def test_tables_show_the_current_system_and_every_visited_system(tmp_path):
    """The current system's planets show the uploaded name with the generated one, translated type, weather,
    gas, sentinels for the save's combat timer, resources with icons; the visited-systems table lists the
    current system first, then systems with resources, then save-only systems, each row clickable;
    recorded planets get their own sub-tab."""
    history = recorded_toxic_planet(tmp_path)
    ctx = planets_view.Context(LiveIn98(), history, visits_from_save(save_with_visits()), FakeGameData(), "Normal",
                               bases=[{"name": "Home", "system": SYSTEM_98}])
    tabs = planets_view.systems_tabs(ctx, None)
    assert [t["id"] for t in tabs["tabs"]] == ["current", "visited", "planets", "galaxy", "trade"]
    current_map, current = tabs["tabs"][0]["sections"]
    assert current_map["type"] == "orbit" and current_map["id"] == "current-map"
    assert current["title"] == "Planets of Delta Sol (live from the game)" and "Gas" in current["columns"]
    row = current["rows"][0]
    assert row[:3] == ["Corrodia (Yaksh Primus)", "Noxious Planet (Ungesunder Planet)", "Poison Rain (Giftregen)"]
    assert row[3] == {"text": "Copper (Kupfer)", "icon": "substance.yellow.2.png"} and row[5] == "Sodium (Natrium)"
    assert row[6] == "Fungal Mould" and row[7] == "Nitrogen (Stickstoff)"
    assert row[10] == "Require Obedience (Erwarten Gehorsam)"
    where = {i["label"]: i["value"] for i in planets_view.where_you_are(ctx)["items"]}
    assert where == {"System": "Delta Sol", "Portal address": "006202925E80", "Galaxy": "Euclid",
                     "Planet": "Corrodia (Yaksh Primus)", "Found by": "your position in the game's memory"}
    system_map, systems = tabs["tabs"][1]["sections"]
    assert tabs["tabs"][1]["badge"] == 2
    assert systems["title"] == "Visited systems (2)" and systems["rows"][0][0] == "Delta Sol" and systems["rows"][0][7] == "yes"
    assert systems["rows"][1][0] == "System 007302925E80" and systems["rows"][1][3] is None
    assert systems["row_action"] == "open_system" and systems["row_keys"] == [f"{SYSTEM_98:x}", f"{SYSTEM_115:x}"]
    assert systems["selected_key"] == f"{SYSTEM_98:x}" and system_map["id"] == "system-map"
    planets = tabs["tabs"][2]["sections"][0]
    assert planets["title"] == "Visited planets with resources (1)" and planets["rows"][0][0] == "Delta Sol"
    assert len(planets["columns"]) == 12 and planets["rows"][0][8] == "Nitrogen (Stickstoff)"


def test_system_map_shows_the_star_and_every_known_planet(tmp_path):
    """The map's star carries the system's facts (portal, galaxy, bases, who named it); each planet is a
    body coloured by biome with its resources, gas and discoveries; planets known only from the save
    appear as 'not scanned yet'; the planet you stand on is marked."""
    history = recorded_toxic_planet(tmp_path)
    visits = visits_from_save(save_with_visits())
    visits[SYSTEM_98]["planets"][2] = {"name": "Far Rock", "minerals": 3}
    ctx = planets_view.Context(LiveIn98(), history, visits, FakeGameData(), "Normal",
                               bases=[{"name": "Home", "system": SYSTEM_98}, {"name": "Elsewhere", "system": SYSTEM_115}])
    orbit = planets_view.system_map(SYSTEM_98, ctx, "system-map", "System map")
    assert orbit["title"] == "System map: Delta Sol"
    star = {i["label"]: i["value"] for i in orbit["center"]["items"]}
    assert star["You are"] == "in this system now" and star["Portal address"] == "006202925E80"
    assert star["Your bases here"] == "Home" and star["Named by"] == "Charlie Papa"
    assert star["System index"] == "98 (0x062)" and star["Planets known"] == "2 (1 with resources)"
    toxic, far = orbit["bodies"]
    assert toxic["label"] == "Corrodia (Yaksh Primus)" and toxic["sublabel"] == "Toxic · Medium"
    assert toxic["color"] == planets_view.BIOME_COLORS["Toxic"] and toxic["size"] == planets_view.SIZE_SCALE["Medium"]
    items = {i["label"]: i["value"] for i in toxic["items"]}
    assert items["You are"] == "on this planet now" and items["Gas (atmosphere harvester)"] == "Nitrogen (Stickstoff)"
    assert items["Your discoveries"] == "1 flora, 2 fauna" and items["Resources"] == "Copper (Kupfer), Ammonia (Ammoniak), Sodium (Natrium)"
    assert {"text": "Copper (Kupfer)", "icon": "substance.yellow.2.png"} in toxic["badges"]
    assert "Nitrogen (Stickstoff)" in toxic["badges"]
    assert far["label"] == "Far Rock" and far["sublabel"] == "not scanned yet" and "color" not in far
    assert {"label": "Your discoveries", "value": "3 minerals"} in far["items"]


@pytest.mark.parametrize("biome, gas", [("Lush", "GAS3"), ("Toxic", "GAS3"), ("Scorched", "GAS1"), ("Barren", "GAS1"),
                                        ("Lava", "GAS1"), ("Radioactive", "GAS2"), ("Frozen", "GAS2"),
                                        ("Exotic (red)", "OXYGEN"), ("Dead", None), ("Gas giant", None), (None, None)])
def test_gas_follows_the_biome(biome, gas):
    """Atmosphere harvesters collect sulphurine (GAS1), radon (GAS2), nitrogen (GAS3) or oxygen by biome;
    the gas id also joins the resource ids, so its icon is extracted with the others."""
    planet = {"biome": biome, "common": "YELLOW2"}
    assert planets_view.planet_gas(planet) == gas
    assert planets_view.resource_ids([planet]) == ["YELLOW2"] + ([gas] if gas else [])


def test_special_systems_are_named_on_the_star(tmp_path):
    """System index 0x79 is the black hole system, 0x7A an Atlas interface, 0x3E8-0x429 purple stars."""
    class Live:
        status, error, current_system, current = "not-running", None, None, None
    ctx = planets_view.Context(Live(), PlanetHistory(tmp_path / "h.json"), {}, FakeGameData(), None)
    for index, special, color in ((0x79, "the region's black hole system", planets_view.STAR_COLOR),
                                  (0x7A, "an Atlas interface system", planets_view.STAR_COLOR),
                                  (0x3E8, "purple star", planets_view.PURPLE_STAR)):
        star = planets_view.system_map(index << 40, ctx, "m", "Map")["center"]
        assert {"label": "Special", "value": special} in star["items"] and star["color"] == color


def test_tables_explain_when_the_game_is_not_running(tmp_path):
    """Without the game the view says how live data appears, and still lists the save's visited systems."""
    class Live:
        status, error, current_system, current = "not-running", None, None, None
    ctx = planets_view.Context(Live(), PlanetHistory(tmp_path / "h.json"), visits_from_save(save_with_visits()),
                               FakeGameData(), None)
    current, visited, planets, _galaxy, _trade = planets_view.systems_tabs(ctx, None)["tabs"]
    assert current["sections"][0]["type"] == "notice" and "Start No Man's Sky" in current["sections"][0]["text"]
    assert planets_view.where_you_are(ctx) is None
    # Without a current system the map shows the clicked system, else the newest one.
    assert visited["sections"][0]["title"] == "System map: Delta Sol" and visited["sections"][1]["title"] == "Visited systems (2)"
    clicked = planets_view.systems_tabs(ctx, SYSTEM_115)["tabs"][1]["sections"]
    assert clicked[0]["title"] == "System map: System 007302925E80" and clicked[1]["selected_key"] == f"{SYSTEM_115:x}"
    assert "every system you visit" in planets["sections"][0]["empty"]


# --------------------------------------------------------------------------- position without the player state


def test_current_system_is_judged_from_the_planets_in_memory():
    """The system with the most planet records is the one you are in (a reused slot of the previous system
    loses the vote); ties go to the lowest key so the answer does not flicker; no planets -> unknown."""
    planets = [{"system": SYSTEM_98}] * 5 + [{"system": SYSTEM_115}]
    assert memory.current_system_from_planets(planets) == SYSTEM_98
    assert memory.current_system_from_planets([{"system": SYSTEM_115}, {"system": SYSTEM_98}]) == SYSTEM_98
    assert memory.current_system_from_planets([]) is None


def test_scan_reports_where_each_planet_record_lives_and_its_seed():
    """A scan returns the address of every planet record, so a warp can be noticed by re-reading 8 bytes per
    planet; each record carries its generation seed (the planet's identity), and planet_system_at reads a
    slot's system back - None once the slot holds no planet."""
    region = bytearray(0x10000)
    region[0x1000:0x1000 + memory.PLANET_SIZE] = planet_blob(seed=0xABCDEF)
    reader = FakeReader({0x100000: region})
    result = memory.scan(reader, SUBSTANCES, None)
    assert result.slots == [0x101000] and result.planets[0]["seed"] == "0000000000abcdef"
    assert memory.planet_system_at(reader, 0x101000) == SYSTEM_98
    region[0x1000:0x1000 + memory.PLANET_SIZE] = bytes(memory.PLANET_SIZE)
    assert memory.planet_system_at(reader, 0x101000) is None


def test_live_memory_without_a_player_state_uses_the_planets_and_watches_their_slots(tmp_path):
    """No player state (the usual case after a game restart): the current system comes from the planet
    records ('planets'), and when the remembered slots switch to another system - a warp - a scan runs at
    once and again after the follow-up delay, without waiting for the 5-minute rescan."""
    region = bytearray(0x10000)
    region[0x1000:0x1000 + memory.PLANET_SIZE] = planet_blob()
    reader = FakeReader({0x100000: region})
    calls = {"n": 0}

    def counting_scan(r, s, a):
        calls["n"] += 1
        return memory.scan(r, s, a)

    live = LiveMemory(PlanetHistory(tmp_path / "h.json"), opener=lambda p: reader, pid_finder=lambda: 4242,
                      scanner=counting_scan)
    live.tick(b"anchor-not-in-memory", SUBSTANCES, 0)
    assert calls["n"] == 1 and live.current_system == SYSTEM_98 and live.current_source == "planets"
    assert live.current is None and live.slots == [0x101000]
    live.tick(b"anchor-not-in-memory", SUBSTANCES, 10)
    assert calls["n"] == 1
    region[0x1000:0x1000 + memory.PLANET_SIZE] = planet_blob("Itwi A1", 5, system=SYSTEM_115,
                                                              ids=("YELLOW2", "DUSTY1", "CATALYST1"))
    live.tick(b"anchor-not-in-memory", SUBSTANCES, 20)
    assert calls["n"] == 2 and live.current_system == SYSTEM_115
    live.tick(b"anchor-not-in-memory", SUBSTANCES, 20 + live_mod.FOLLOW_UP_S)
    assert calls["n"] == 3


def test_a_player_state_copy_whose_memory_was_reused_is_dropped(tmp_path):
    """The player state is trusted only while the save's start addresses still sit in front of it: once the
    game overwrites that memory, its address field is not read as your position (it would be garbage that
    can look valid); the plugin falls back to judging from the planets."""
    state, anchor = player_state_region(current=(1, 98))
    planets = bytearray(0x10000)
    planets[0x1000:0x1000 + memory.PLANET_SIZE] = planet_blob("Itwi A1", 5, system=SYSTEM_115,
                                                               ids=("YELLOW2", "DUSTY1", "CATALYST1"))
    reader = FakeReader({0x600000: state, 0x100000: planets})
    live = LiveMemory(PlanetHistory(tmp_path / "h.json"), opener=lambda p: reader, pid_finder=lambda: 4242,
                      scanner=lambda r, s, a: memory.scan(r, s, a))
    live.tick(anchor, SUBSTANCES, 0)
    assert live.current_source == "player" and live.current_system == SYSTEM_98
    state[0x40:0x40 + len(anchor)] = bytes(len(anchor))        # the game reused that memory
    live.tick(anchor, SUBSTANCES, 5)
    assert live.player_state is None and live.current_source == "planets" and live.current_system == SYSTEM_115


# --------------------------------------------------------------------------- renamed planets


def test_a_renamed_planet_replaces_its_old_entry(tmp_path):
    """The same planet (same address and seed) read under a new name - renamed in the game or an uploaded
    name arriving - takes over its entry: one planet, first_seen kept, the old name remembered; not a
    duplicate that stays forever."""
    history = PlanetHistory(tmp_path / "h.json")
    first = memory.parse_planet(bytes(planet_blob("Neu: Cutumus", 2, seed=0x77)))
    history.record([first], "2026-10-04T08:00:00", SYSTEM_98)
    again = memory.parse_planet(bytes(planet_blob("Cutumus", 2, seed=0x77)))
    history.record([again], "2026-10-04T09:00:00", SYSTEM_98)
    planets = history.systems()[SYSTEM_98]
    assert [p["name"] for p in planets] == ["Cutumus"]
    assert planets[0]["first_seen"] == "2026-10-04T08:00:00" and planets[0]["previous_names"] == ["Neu: Cutumus"]
    assert history.scans[-1]["renamed"] == 1 and history.scans[-1]["new"] == 0


def test_a_different_planet_with_the_same_resources_is_not_taken_for_a_rename(tmp_path):
    """A reused slot can hold another planet with the same address, index, biome and resources; a different
    seed keeps the two apart, so the earlier system's planet is not lost."""
    history = PlanetHistory(tmp_path / "h.json")
    history.record([memory.parse_planet(bytes(planet_blob("A-one", 0, seed=1)))], "t1", SYSTEM_98)
    stale = memory.parse_planet(bytes(planet_blob("B-one", 0, seed=2)))      # carries system 98's address
    history.record([stale], "t2", SYSTEM_115)
    names = sorted(p["name"] for planets in history.systems().values() for p in planets)
    assert names == ["A-one", "B-one"]


def test_an_old_record_without_a_seed_is_renamed_only_in_its_own_system(tmp_path):
    """Records from before 0.4.0 have no seed: a new name at the same address counts as a rename only when
    that address names the system you are in and the planet looks the same - never for a reused slot."""
    old = memory.parse_planet(bytes(planet_blob("Neu: X", 1)))
    old["seed"] = None
    renamed = memory.parse_planet(bytes(planet_blob("X", 1)))
    history = PlanetHistory(tmp_path / "h.json")
    history.record([dict(old)], "t1", SYSTEM_98)
    history.record([dict(renamed)], "t2", SYSTEM_115)           # elsewhere: could be a reused slot
    names = sorted(p["name"] for planets in history.systems().values() for p in planets)
    assert names == ["Neu: X", "X"]
    history2 = PlanetHistory(tmp_path / "h2.json")
    history2.record([dict(old)], "t1", SYSTEM_98)
    history2.record([dict(renamed)], "t2", SYSTEM_98)
    assert [p["name"] for p in history2.systems()[SYSTEM_98]] == ["X"]


def test_where_you_are_says_when_the_planet_is_unknown(tmp_path):
    """Judged from the planets, the system is shown but the planet is 'unknown', not 'in space', and the
    page says how the position was found."""
    class Live:
        status, error, current, current_system, current_source = "ok", None, None, SYSTEM_98, "planets"
    ctx = planets_view.Context(Live(), PlanetHistory(tmp_path / "h.json"), {}, FakeGameData(), None)
    where = {i["label"]: i["value"] for i in planets_view.where_you_are(ctx)["items"]}
    assert where["Planet"].startswith("unknown") and where["Found by"].startswith("the planets")
