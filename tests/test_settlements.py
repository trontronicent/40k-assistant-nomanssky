"""Tests for the Settlements tab: the game's settlement tables, the save's settlement economy, the view."""

import struct

from nms_connector import mbin, settlements, timers

LAST_JUDGEMENT = 1_791_113_351      # 2026-10-04 13:29:11, Kay City (live save)
MARK = mbin.MARK


def settlement_globals(header=timers.MBIN_HEADER, wait=(900, 7200), npcs=30) -> bytes:
    """gcsettlementglobals.mbin with the stat ranges, thresholds, decision wait and NPC cap at their offsets."""
    data = bytearray(header + settlements.MAX_NPC_AT + 64)
    f = settlements.FALLBACK
    struct.pack_into("<8i", data, header + settlements.STATS_MAX_AT, *f["stats_max"])
    struct.pack_into("<8i", data, header + settlements.STATS_MIN_AT, *f["stats_min"])
    struct.pack_into("<8f", data, header + settlements.BAD_AT, *f["bad"])
    struct.pack_into("<8f", data, header + settlements.GOOD_AT, *f["good"])
    struct.pack_into("<2i", data, header + settlements.JUDGEMENT_WAIT_AT, wait[1], wait[0])
    struct.pack_into("<i", data, header + settlements.MAX_NPC_AT, npcs)
    return bytes(data)


def perks_table(perks, record=settlements.PERK_RECORD) -> bytes:
    """settlementperkstable.mbin: a root list of GcSettlementPerkData records whose StatChanges lists follow them.
    ``perks`` is [(id, name key, desc key, flags (blessing, job, negative, proc, starter), [(stat, strength)])]."""
    root, start = 0x10, 0x20
    end = start + record * len(perks)
    data = bytearray(end + 0xC * sum(len(p[4]) for p in perks) + 0x10)
    struct.pack_into("<QI4s", data, root, start - root, len(perks), MARK)
    tail = end
    for k, (pid, name, desc, flags, changes) in enumerate(perks):
        p = start + k * record
        data[p:p + len(desc)] = desc.encode()
        data[p + 0x20:p + 0x20 + len(name)] = name.encode()
        data[p + 0x50:p + 0x50 + len(pid)] = pid.encode()
        struct.pack_into("<QI4s", data, p + 0x60, tail - (p + 0x60), len(changes), MARK)
        for stat, strength in changes:
            struct.pack_into("<IIB", data, tail, settlements.STATS.index(stat), strength, 0)
            tail += 0xC
        data[p + 0x70:p + 0x75] = bytes(flags)
    return bytes(data)


PERKS = [
    ("STARTING_NEG9", "UI_PERK_NEGATIVE_TITLE_9", "UI_PERK_NEGATIVE_DESC_COST", (0, 0, 1, 0, 1), [("Upkeep", 5)]),
    ("PROC_BAR", "UI_SETTLEMENT_PERK_PROC_3", "UI_PERK_POSITIVE_DESC_MOOD", (0, 0, 0, 1, 0),
     [("Happiness", 0), ("Production", 4)]),
]


def test_the_settlement_tables_are_read_at_the_libmbin_offsets_and_checked():
    """Stat ranges, the 15 min to 2 h wait between decisions and the NPC cap come from GcSettlementGlobals; a
    shifted read (a game update) is refused, so the tab falls back to the measured values instead of nonsense."""
    tables = settlements.parse_globals(settlement_globals())
    assert tables["stats_max"][1] == 180 and tables["stats_min"][1] == -30
    assert tables["judgement_wait"] == [900, 7200] and tables["max_npcs"] == 30
    assert settlements.parse_globals(settlement_globals(header=0x24)) is None
    assert settlements.parse_globals(settlement_globals(wait=(7200, 900))) is None
    assert settlements.parse_globals(b"short") is None
    fallback = settlements.load_tables(None)
    assert fallback["judgement_wait"] == [900, 7200] and fallback["perks"] == {} and "not found" in fallback["error"]


def test_perks_are_read_with_their_effects_as_better_or_worse():
    """A perk's strength says better or worse for you, not up or down: the game describes STARTING_NEG9
    (Upkeep NegativeMedium) as 'Increases maintenance costs'. A table with another record size is refused."""
    perks = settlements.parse_perks(perks_table(PERKS))
    assert perks["STARTING_NEG9"]["changes"] == [("Upkeep", "worse (medium)")]
    assert perks["STARTING_NEG9"]["negative"] and perks["STARTING_NEG9"]["starter"]
    assert perks["PROC_BAR"]["changes"] == [("Happiness", "better (varies)"), ("Production", "worse (small)")]   # the bar: happier, a bit less productive
    assert perks["PROC_BAR"]["procedural"] and perks["PROC_BAR"]["name"] == "UI_SETTLEMENT_PERK_PROC_3"
    assert settlements.parse_perks(perks_table(PERKS, record=0x80)) == {}
    assert settlements.parse_perks(b"\0" * 64) == {}


def save(*states) -> dict:
    return {"BaseContext": {"PlayerStateData": {
        "PersistentPlayerBases": [{"Owner": {"UID": "me"}}], "SettlementStatesV2": list(states)}}}


def kay_city(owner="me", pending="None", building="Settlement_Farm"):
    return {"Name": "Kay City", "Owner": {"UID": owner}, "Race": {"AlienRace": "Explorers"}, "Population": 20,
            "Stats": [0, 36, 84308, -3250, 0, 931025, 338, 552],
            "ProductionState": [{"ElementId": "^GAS2", "Amount": 120, "ProductionAccumulationCap": 1500,
                                 "LastChangeTimestamp": LAST_JUDGEMENT}, {"ElementId": "", "Amount": 0}],
            "Perks": ["^STARTING_NEG9", "^PROC_BAR#66265", "^UNKNOWN_PERK"],
            "PendingJudgementType": {"SettlementJudgementType": pending}, "LastJudgementTime": LAST_JUDGEMENT,
            "NextBuildingUpgradeClass": {"BuildingClass": building}}


def test_only_your_settlements_are_read_with_stats_production_and_perks():
    """Settlements of other players (visited ones are in the save too) are left out; empty production slots
    are skipped and the construction in progress gets the terminal's building name."""
    items = settlements.settlements_from_save(save(kay_city(), kay_city(owner="friend")))
    assert len(items) == 1
    s = items[0]
    assert s["population"] == 20 and s["race"] == "Explorers" and s["stats"][5] == 931025
    assert s["production"] == [{"item": "GAS2", "amount": 120, "cap": 1500, "at": LAST_JUDGEMENT}]
    assert s["building"] == "Farm" and s["pending"] == "None"
    assert settlements.perk_id("^PROC_BAR#66265") == "PROC_BAR"
    assert settlements.settlements_from_save({}) == []


class FakeTexts:
    """Texts stand-in: known keys get a name, items get a cell."""
    NAMES = {"UI_PERK_NEGATIVE_TITLE_9": "Built on fault line", "UI_PERK_NEGATIVE_DESC_COST": "Increases maintenance costs",
             "UI_SETTLEMENT_PERK_PROC_3": "%BAR_ADJ% %BAR%", "UI_PERK_POSITIVE_DESC_MOOD": "Improves citizen happiness"}

    def key(self, key, sibling=None):
        return self.NAMES.get(key, key)

    def item(self, item_id, text=None):
        return {"text": f"item {item_id}"}


def tables():
    return dict(settlements.FALLBACK, perks=settlements.parse_perks(perks_table(PERKS)))


def test_the_tab_shows_the_decision_window_stats_production_and_perks():
    """The next decision is a window (the game draws the wait between 15 min and 2 h), stats sit on the game's
    range, procedural perks (names built from a seed) are shown by their description, unknown perks by id."""
    items = settlements.settlements_from_save(save(kay_city()))
    out = settlements.settlement_sections(items, tables(), FakeTexts(), LAST_JUDGEMENT + 60)
    status = next(s for s in out if s.get("title") == "Kay City")
    values = {i["label"]: i["value"] for i in status["items"]}
    assert values["Next decision"].startswith("between ") and "15 min to 2 h" in values["Next decision"]
    assert values["Construction"] == "Farm" and values["Population"].startswith("20 ")
    stats = next(s for s in out if s.get("title") == "Kay City: stats")
    assert ["Happiness", None, "36", "-30 to 180"] in stats["rows"]          # without the game: the save's values
    assert ["Debt", None, "931'025", "0 to 10'000'000"] in stats["rows"]
    production = next(s for s in out if s.get("title") == "Kay City: production")
    assert production["rows"][0][:3] == [{"text": "item GAS2"}, "120", "1'500"]
    perks = next(s for s in out if s.get("title") == "Kay City: perks")["rows"]
    assert perks[0] == [{"text": "Built on fault line", "hint": "Increases maintenance costs"}, "negative",
                        "Maintenance worse (medium)", "founding"]
    assert perks[1][0] == "Improves citizen happiness (named in the game)" and perks[1][3] == "a decision"
    assert perks[2][0] == "UNKNOWN_PERK"
    job = dict(FakeTexts.NAMES, UI_JOB="%JOB_ADJ% %JOB%", UI_JOB_DESC="%JOB_STAT% increased")
    texts = FakeTexts()
    texts.NAMES = job
    tables_with_job = tables()
    tables_with_job["perks"]["PROC_JOB"] = {"name": "UI_JOB", "description": "UI_JOB_DESC", "negative": False, "job": True,
                                            "blessing": False, "procedural": True, "starter": False,
                                            "changes": [("Production", "better (varies)")]}
    state = dict(kay_city(), Perks=["^PROC_JOB#33770"])
    rows = next(s for s in settlements.settlement_sections(settlements.settlements_from_save(save(state)), tables_with_job,
                                                           texts, LAST_JUDGEMENT) if s.get("title") == "Kay City: perks")["rows"]
    assert rows[0][0] == "A job (named in the game)"     # no "%JOB_STAT%" placeholder shown


def test_the_decision_line_follows_the_clock_and_a_waiting_decision():
    """Once the window has opened the line says 'by ... at the latest', after it 'any time now'; a decision
    already waiting is said so with its kind instead."""
    def line(state, now):
        items = settlements.settlements_from_save(save(state))
        status = settlements.settlement_sections(items, tables(), FakeTexts(), now)[1]
        return next(i["value"] for i in status["items"] if i["label"] == "Next decision")

    assert line(kay_city(), LAST_JUDGEMENT + 1000).startswith("by ")
    assert line(kay_city(), LAST_JUDGEMENT + 8000).startswith("any time now")
    assert line(kay_city(pending="StrangerVisit"), LAST_JUDGEMENT) == "waiting for you (Stranger visit)"
    assert settlements.settlement_sections([], tables(), FakeTexts(), 0)[0]["text"] == settlements.EMPTY


SEED = 0x5E3651AAEADBCE06
SCREEN = [52, 41, 489454, 395010, 0, 908027, 358, 552]     # Kay City's settlement screen, 2026-10-04


class FakeMemory:
    """One region holding a settlement's computed-stats record at `at` (read-only reader + chunker)."""

    def __init__(self, at=0x1008, stats=SCREEN, seed=SEED, size=0x4000):
        self.buf = bytearray(size)
        record = settlements.seed_needle(seed) + struct.pack("<2i8i", 1, 0, *stats)
        self.buf[at:at + len(record)] = record
        self.base, self.searches = 0x1666B580000, 0

    def read(self, address, size):
        off = address - self.base
        return bytes(self.buf[off:off + size]) if 0 <= off < len(self.buf) else None

    def chunks(self, reader, overlap=0):
        self.searches += 1
        yield self.base, self.base, self.buf, len(self.buf), len(self.buf)


def test_the_settlement_screen_values_are_found_by_the_seed_pair_and_re_read():
    """The screen's values exist only in the game's memory, right after the settlement's seed stored twice.
    The first tick searches, later ticks re-read 56 bytes; a record that is gone (freed, game restarted) is
    searched again at most once a minute, and the last reading is kept with its time."""
    mem = FakeMemory()
    now = [1000.0]
    live = settlements.LiveSettlements(chunker=mem.chunks, clock=lambda: now[0])
    live.tick(mem, [SEED])
    assert live.addresses == {SEED: mem.base + 0x1008} and live.values[SEED] == {"stats": SCREEN, "at": 1000.0}
    now[0] += 5
    live.tick(mem, [SEED])
    assert mem.searches == 1 and live.values[SEED]["at"] == 1005.0
    mem.buf[0x1008:0x1010] = b"\0" * 8                       # freed
    now[0] += 5
    live.tick(mem, [SEED])
    assert SEED not in live.addresses and mem.searches == 1 and live.values[SEED]["at"] == 1005.0
    now[0] += settlements.SEARCH_EVERY_S
    live.tick(mem, [SEED])
    assert mem.searches == 2 and SEED not in live.addresses


def test_a_seed_pair_followed_by_nonsense_is_not_taken_for_the_stats():
    """The seed alone is no proof: a population capacity of 0 or values far outside the game's ranges mean
    another structure, and parse_live refuses it."""
    assert settlements.parse_live(FakeMemory().read(0x1666B580000 + 0x1008, settlements.LIVE_SIZE), SEED) == SCREEN
    bad = FakeMemory(stats=[0, 41, 489454, 395010, 0, 908027, 358, 552])
    assert settlements.parse_live(bad.read(bad.base + 0x1008, settlements.LIVE_SIZE), SEED) is None
    assert settlements.parse_live(FakeMemory(seed=SEED + 1).read(0x1666B580000 + 0x1008, 0x38), SEED) is None
    assert settlements.parse_live(None, SEED) is None
    # Seen live 2026-10-04: the seed in front of other data that looks like stats; the marker ints tell it apart.
    lookalike = settlements.seed_needle(SEED) + struct.pack("<2i8i", 36, 46, 41, 41, 41, 41, 50, 39, 39, 39)
    assert settlements.parse_live(lookalike, SEED) is None


def test_the_stats_table_shows_the_screen_values_like_the_game():
    """With a live reading the table writes each stat as the settlement screen does - 20 / 52, 34 % happiness
    ((41 + 30) / 210), 489'454 units/day, alert 36 % - next to what the save stores; without one it says the
    game must run."""
    state = dict(kay_city(), SeedValue="0x5E3651AAEADBCE06")
    items = settlements.settlements_from_save(save(state))
    assert items[0]["seed"] == SEED
    out = settlements.settlement_sections(items, tables(), FakeTexts(), 2000, {SEED: {"stats": SCREEN, "at": 1990}})
    stats = next(s for s in out if s.get("title") == "Kay City: stats")
    assert stats["columns"][1] == "In the game (now)"
    rows = {r[0]: r[1:3] for r in stats["rows"]}
    assert rows["Population capacity"] == ["20 / 52", "0"] and rows["Happiness"] == ["34 %", "36"]
    assert rows["Productivity"] == ["489'454 units/day", "84'308"] and rows["Maintenance"][0] == "395'010 units/day"
    assert rows["Sentinel alert"][0] == "36 %"
    later = settlements.settlement_sections(items, tables(), FakeTexts(), 9000, {SEED: {"stats": SCREEN, "at": 1990}})
    assert next(s for s in later if s.get("title") == "Kay City: stats")["columns"][1].startswith("In the game (at ")
    none = settlements.settlement_sections(items, tables(), FakeTexts(), 2000)
    stats = next(s for s in none if s.get("title") == "Kay City: stats")
    assert "visit the settlement" in stats["columns"][1] and stats["rows"][1][1] is None


def test_the_last_screen_values_survive_a_restart(tmp_path):
    """The record exists only while you are at the settlement, so the last reading is written to the plugin's
    data folder and read back by the next start; a damaged file starts empty and says why."""
    path = tmp_path / "settlement_screen.json"
    mem = FakeMemory()
    settlements.LiveSettlements(path, chunker=mem.chunks, clock=lambda: 1000.0).tick(mem, [SEED])
    again = settlements.LiveSettlements(path)
    assert again.values == {SEED: {"stats": SCREEN, "at": 1000.0}}
    path.write_text("{broken", encoding="utf-8")
    broken = settlements.LiveSettlements(path)
    assert broken.values == {} and "JSONDecodeError" in broken.load_error


def test_stats_and_perks_carry_the_settlement_screens_icons():
    """Each stat row gets the screen's icon for that stat, each perk the positive or negative icon of the stat
    it mainly changes - when the icon has been converted (the plugin's GameData knows it)."""
    class Gamedata:
        def icon_name(self, icon_id):
            return icon_id.lower() + ".png"

    texts = FakeTexts()
    texts.gamedata = Gamedata()
    out = settlements.settlement_sections(settlements.settlements_from_save(save(kay_city())), tables(), texts, LAST_JUDGEMENT)
    stats = next(s for s in out if s.get("title") == "Kay City: stats")
    assert stats["rows"][1][0] == {"text": "Happiness", "icon": "settlement_basic_happiness.png"}
    perks = next(s for s in out if s.get("title") == "Kay City: perks")["rows"]
    assert perks[0][0]["icon"] == "settlement_negative_maintenance.png"      # fault line: maintenance worse
    assert perks[1][0]["icon"] == "settlement_positive_happiness.png"
    assert settlements.stat_icon_id("Upkeep", "negative") == "SETTLEMENT_NEGATIVE_MAINTENANCE"
