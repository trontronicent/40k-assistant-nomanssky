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
    scale, procedural perks (names built from a seed) are shown by their description, unknown perks by id."""
    items = settlements.settlements_from_save(save(kay_city()))
    out = settlements.settlement_sections(items, tables(), FakeTexts(), LAST_JUDGEMENT + 60)
    status = next(s for s in out if s.get("title") == "Kay City")
    values = {i["label"]: i["value"] for i in status["items"]}
    assert values["Next decision"].startswith("between ") and "15 min to 2 h" in values["Next decision"]
    assert values["Construction"] == "Farm" and values["Population"].startswith("20 ")
    stats = next(s for s in out if s.get("title") == "Kay City: stats")
    assert ["Happiness", "36", "31 %", "-30 to 180"] in stats["rows"]
    assert ["Debt", "931'025", "9 %", "0 to 10'000'000"] in stats["rows"]
    production = next(s for s in out if s.get("title") == "Kay City: production")
    assert production["rows"][0][:3] == [{"text": "item GAS2"}, "120", "1'500"]
    perks = next(s for s in out if s.get("title") == "Kay City: perks")["rows"]
    assert perks[0] == [{"text": "Built on fault line", "hint": "Increases maintenance costs"}, "negative",
                        "Maintenance worse (medium)", "founding"]
    assert perks[1][0] == "Improves citizen happiness (named in the game)" and perks[1][3] == "a decision"
    assert perks[2][0] == "UNKNOWN_PERK"


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
