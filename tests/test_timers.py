"""Tests for timers from the save: settlement constructions, frigate expeditions, the game's tables, the view."""

import struct

from nms_connector import timers

START = 1_791_107_277          # 2026-10-04 11:47:57, Kay City's factory (live save)
EXPEDITION = 1_791_102_360     # 2026-10-04 10:26:00


def settlement_globals(factory=5600, farm=5600, header=timers.MBIN_HEADER) -> bytes:
    """gcsettlementglobals.mbin with SettlementBuildingTimes at its libMBIN offset."""
    data = bytearray(header + timers.BUILDING_TIMES_AT + 63 * 8 + 64)
    times = [0] * 63
    times[timers.BUILDING_CLASSES.index("Settlement_Factory")] = factory
    times[timers.BUILDING_CLASSES.index("Settlement_Farm")] = farm
    struct.pack_into("<63Q", data, header + timers.BUILDING_TIMES_AT, *times)
    return bytes(data)


def fleet_globals(event=5400, easy=900) -> bytes:
    data = bytearray(timers.MBIN_HEADER + timers.EVENT_TIME_EASY_AT + 16)
    struct.pack_into("<2i", data, timers.MBIN_HEADER + timers.EVENT_TIME_AT, event, easy)
    return bytes(data)


def test_tables_are_read_at_the_libmbin_offsets_and_checked():
    """Building times (per building class) and the expedition event time come from the game's globals files;
    a layout that moved (values in the wrong place) is refused, so the measured fallback is used instead of
    nonsense end times."""
    tables = timers.parse_tables(settlement_globals(), fleet_globals())
    assert tables["building_times"] == {"Settlement_Farm": 5600, "Settlement_Factory": 5600}
    assert tables["event_seconds"] == 5400 and tables["event_seconds_easy"] == 900 and tables["source"] == "game files"
    assert timers.parse_tables(settlement_globals(header=0x28), fleet_globals()) is None       # shifted by one entry
    assert timers.parse_tables(settlement_globals(), fleet_globals(event=-1)) is None
    assert timers.parse_tables(b"short", b"short") is None
    fallback = timers.load_tables(None)
    assert fallback["building_times"]["Settlement_Factory"] == 5600 and "not found" in fallback["error"]


def save(settlements=(), expeditions=()) -> dict:
    return {"BaseContext": {"PlayerStateData": {
        "PersistentPlayerBases": [{"Owner": {"UID": "me"}}, {"Owner": {"UID": "me"}}, {"Owner": {"UID": "friend"}}],
        "SettlementStatesV2": list(settlements), "FleetExpeditions": list(expeditions)}}}


def settlement(owner="me", slot=27, stamp=START, kind="Settlement_Factory", name="Kay City"):
    stamps = [0] * 48
    stamps[slot] = stamp
    return {"UniqueId": "5e3651aaeadbce06", "Name": name, "Owner": {"UID": owner}, "NextBuildingUpgradeIndex": slot,
            "NextBuildingUpgradeClass": {"BuildingClass": kind}, "LastBuildingUpgradesTimestamps": stamps}


def expedition(events=6, next_event=1, last_change=EXPEDITION + 5400, pause=0):
    return {"Seed": [True, "0x39239E8F68C6A041"], "StartTime": EXPEDITION, "PauseTime": pause, "TimeOfLastUAChange": last_change,
            "NextEventToTrigger": next_event, "Events": [{}] * events, "AllFrigateIndices": [2],
            "ExpeditionCategory": {"ExpeditionCategory": "Balanced"}, "ExpeditionDuration": {"ExpeditionDuration": "Short"}}


def test_the_settlement_construction_in_progress_ends_after_its_building_time():
    """Seen live 2026-10-04: Kay City's factory (slot 27) started 11:47:57 and takes 5600 s, so it ends 13:21:17.
    Settlements of other players, unknown building classes and slots without a start time give no timer."""
    tables = timers.FALLBACK
    found = timers.timers_from_save(save([settlement(), settlement(owner="friend", name="Not mine"),
                                          settlement(kind="Settlement_Unknown"), settlement(stamp=0)]), tables)
    assert found == [{"key": "settlement.5e3651aaeadbce06.27", "label": "Kay City: Factory built",
                      "started_at": START, "ends_at": START + 5600,
                      "detail": "Settlement construction (building 28), 93 min"}]


def test_an_expedition_returns_after_its_last_event():
    """Seen live 2026-10-04: a 6-event expedition started 10:26:00 with one event every 5400 s returns at
    19:26:00; the detail names the next event. A paused expedition (end unknown) gives no timer, and an early
    'easy' expedition (900 s per event, told by the save's own times) ends sooner."""
    (timer,) = timers.timers_from_save(save(expeditions=[expedition()]), timers.FALLBACK)
    assert timer["key"] == "expedition.39239e8f68c6a041" and timer["ends_at"] == EXPEDITION + 6 * 5400
    assert timer["label"] == "Frigate expedition returns (1 frigate)"
    assert timer["detail"].startswith("Balanced Short, 6 events, 1 done; next event 2 of 6 at ")
    assert timers.timers_from_save(save(expeditions=[expedition(pause=EXPEDITION + 60)]), timers.FALLBACK) == []
    easy = timers.timers_from_save(save(expeditions=[expedition(last_change=EXPEDITION + 225 * 3)]), timers.FALLBACK)
    assert easy[0]["ends_at"] == EXPEDITION + 6 * 900
    first_move = timers.timers_from_save(save(expeditions=[expedition(last_change=EXPEDITION + 1350)]), timers.FALLBACK)
    assert first_move[0]["ends_at"] == EXPEDITION + 6 * 5400          # 1350 s fits both: normal wins


def test_the_view_uses_the_timers_section_where_the_app_has_one():
    """Apps from 3.8.0 render a timers section (live countdown, notification bells); older apps get a table of
    end times instead, so the plugin works with both. Timers that ended more than a day ago are left out."""
    items = [{"key": "a", "label": "Soon", "ends_at": START + 60, "started_at": START, "detail": "x"},
             {"key": "b", "label": "Long gone", "ends_at": START - 2 * 86400}]
    modern = timers.timers_section(items, ("table", "timers"), START)
    assert modern["type"] == "timers" and [t["key"] for t in modern["items"]] == ["a"] and modern["empty"]
    old = timers.timers_section(items, ("table",), START)
    assert old["type"] == "table" and old["columns"] == ["What", "Ends", "Details"]
    assert old["rows"] == [["Soon", timers.clock(START + 60), "x"]]
    done = timers.timers_section(items, (), START + 120)
    assert done["rows"][0][1].endswith("(done)")
