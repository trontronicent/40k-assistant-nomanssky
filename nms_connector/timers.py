"""Timers from the save: settlement constructions and frigate expeditions - what finishes when.

The save stores when something started, not when it ends; the durations come from the game's own tables
(``load_tables``, read once per start from the installed game):

- **Settlement construction** (``SettlementStatesV2``): the building project in progress is
  ``NextBuildingUpgradeIndex`` (building slot) of class ``NextBuildingUpgradeClass``, started at
  ``LastBuildingUpgradesTimestamps[slot]``; it takes ``GcSettlementGlobals.SettlementBuildingTimes[class]``
  seconds. Verified 2026-10-04: Kay City's factory (slot 27, class Settlement_Factory = 5600 s) started 11:47:57.
- **Frigate expedition** (``FleetExpeditions``): one event every ``GcFleetGlobals.TimeTakenForExpeditionEvent``
  seconds (5400) from ``StartTime``; it returns after its last event. Verified 2026-10-04: a 6-event "Short"
  expedition started 10:26:00, its first event completed 11:56:00 (= start + 5400, the save's
  TimeOfLastUAChange). Early "easy" expeditions use TimeTakenForExpeditionEvent_Easy (900 s); which one
  applies is told by the save's own event times (``_event_seconds``).

Offsets: libMBIN 7.04 (``/* 0x... */`` comments in GcSettlementGlobals.cs / GcFleetGlobals.cs) plus the
0x20-byte MBIN header - both checked against the installed game on 2026-10-04. Values that do not make
sense fall back to those measured ones (``FALLBACK``), and ``source`` says which were used.
"""

from __future__ import annotations

import struct
from datetime import datetime

MBIN_HEADER = 0x20
SETTLEMENT_FILE = "gcsettlementglobals.mbin"
FLEET_FILE = "gcfleetglobals.global.mbin"
BUILDING_TIMES_AT = 0x99B0          # u64[63] seconds per BuildingClass
EVENT_TIME_AT = 0x1364              # int TimeTakenForExpeditionEvent
EVENT_TIME_EASY_AT = 0x1368         # int TimeTakenForExpeditionEvent_Easy

# GcBuildingClassification.BuildingClassEnum (libMBIN 7.04), in order.
BUILDING_CLASSES = [
    "None", "TerrainResource", "Shelter", "Abandoned", "Terminal", "Shop", "Outpost", "Waypoint", "Beacon",
    "RadioTower", "Observatory", "Depot", "Factory", "Harvester", "Plaque", "Monolith", "Portal", "Ruin", "Debris",
    "DamagedMachine", "DistressSignal", "LandingPad", "Base", "MissionTower", "CrashedFreighter", "GraveInCave",
    "StoryGlitch", "TreasureRuins", "GameStartSpawn", "WaterCrashedFreighter", "WaterTreasureRuins", "WaterAbandoned",
    "WaterDistressSignal", "NPCDistressSignal", "NPCDebris", "LargeBuilding", "Settlement_Hub",
    "Settlement_LandingZone", "Settlement_Bar", "Settlement_Tower", "Settlement_Market", "Settlement_Small",
    "Settlement_SmallIndustrial", "Settlement_Medium", "Settlement_Large", "Settlement_Monument",
    "Settlement_SheriffsOffice", "Settlement_Double", "Settlement_Farm", "Settlement_Factory", "Settlement_Clump",
    "DroneHive", "SentinelDistressSignal", "AbandonedRobotCamp", "RobotHead", "DigSite", "AncientGuardian",
    "Settlement_Hub_Builders", "Settlement_FishPond", "Settlement_Builders_RoboArm", "CargoDrop", "ScrapYard",
    "Crashed_Swarm",
]
BUILDING_NAMES = {   # what the settlement's construction terminal calls them
    "Settlement_Hub": "Settlement hub", "Settlement_LandingZone": "Landing pad", "Settlement_Bar": "Bar",
    "Settlement_Tower": "Tower", "Settlement_Market": "Market", "Settlement_Small": "Small house",
    "Settlement_SmallIndustrial": "Small industrial building", "Settlement_Medium": "Medium house",
    "Settlement_Large": "Large house", "Settlement_Monument": "Monument", "Settlement_SheriffsOffice": "Overseer's office",
    "Settlement_Double": "Double house", "Settlement_Farm": "Farm", "Settlement_Factory": "Factory",
    "Settlement_Clump": "Building group", "Settlement_Hub_Builders": "Builders' hub", "Settlement_FishPond": "Fish pond",
    "Settlement_Builders_RoboArm": "Builders' robot arm",
}
# Measured from the game's files on 2026-10-04 (build 25625620): used when the tables cannot be read.
FALLBACK = {
    "building_times": {"Settlement_LandingZone": 3600, "Settlement_Bar": 3600, "Settlement_Tower": 3600,
                       "Settlement_Market": 7200, "Settlement_Small": 1200, "Settlement_SmallIndustrial": 1200,
                       "Settlement_Medium": 2800, "Settlement_Large": 7200, "Settlement_SheriffsOffice": 90,
                       "Settlement_Double": 3600, "Settlement_Farm": 5600, "Settlement_Factory": 5600,
                       "Settlement_FishPond": 1200, "Settlement_Builders_RoboArm": 3600},
    "event_seconds": 5400, "event_seconds_easy": 900, "source": "built-in (measured 2026-10-04)",
}
DONE_SHOWN_S = 24 * 3600            # a finished timer stays listed this long (as "done")


def parse_tables(settlement: bytes, fleet: bytes) -> dict | None:
    """Building times and expedition event times from the two globals files, or None when they make no sense."""
    try:
        times = struct.unpack_from("<63Q", settlement, MBIN_HEADER + BUILDING_TIMES_AT)
        event, easy = struct.unpack_from("<2i", fleet, MBIN_HEADER + EVENT_TIME_AT)
    except struct.error:
        return None
    building = {name: int(t) for name, t in zip(BUILDING_CLASSES, times) if t}
    # Sanity: only the buildings that have times in today's game, each under a week, and the factory among them.
    # A reading shifted by one entry puts times on classes that have none (hub, building group) and is refused.
    if (not building or not set(building) <= set(FALLBACK["building_times"]) or max(building.values()) > 7 * 86400
            or "Settlement_Factory" not in building or not 60 <= event <= 86400 or not 10 <= easy <= event):
        return None
    return {"building_times": building, "event_seconds": event, "event_seconds_easy": easy, "source": "game files"}


def load_tables(install) -> dict:
    """The timer tables of the installed game, else FALLBACK (``source`` says which, ``error`` why)."""
    from .hgpak import PakError, PakSet, ZstdUnavailable
    if install is None:
        return dict(FALLBACK, error="game installation not found")
    try:
        with PakSet(install.pcbanks, {SETTLEMENT_FILE: "NMSARC.MetadataEtc.pak", FLEET_FILE: "NMSARC.MetadataEtc.pak"}) as paks:
            tables = parse_tables(paks.read(SETTLEMENT_FILE), paks.read(FLEET_FILE))
    except (KeyError, OSError, PakError, ZstdUnavailable) as exc:
        return dict(FALLBACK, error=f"{type(exc).__name__}: {exc}")
    return tables or dict(FALLBACK, error="the game's tables changed layout (a game update?)")


def player_uid(player_state: dict) -> str | None:
    """The save owner's id: the owner of most of their bases."""
    counts: dict[str, int] = {}
    for base in player_state.get("PersistentPlayerBases") or []:
        uid = ((base.get("Owner") or {}).get("UID") or "") if isinstance(base, dict) else ""
        if uid:
            counts[uid] = counts.get(uid, 0) + 1
    return max(counts, key=counts.get) if counts else None


def settlement_timers(player_state: dict, tables: dict) -> list[dict]:
    """The construction in progress (or just finished) in each of your settlements."""
    uid = player_uid(player_state)
    out = []
    for s in player_state.get("SettlementStatesV2") or []:
        if not isinstance(s, dict) or not uid or ((s.get("Owner") or {}).get("UID")) != uid:
            continue
        slot = s.get("NextBuildingUpgradeIndex")
        stamps = s.get("LastBuildingUpgradesTimestamps") or []
        kind = (s.get("NextBuildingUpgradeClass") or {}).get("BuildingClass")
        seconds = tables["building_times"].get(kind)
        if not isinstance(slot, int) or not 0 <= slot < len(stamps) or not stamps[slot] or not seconds:
            continue
        started = int(stamps[slot])
        name = s.get("Name") or "Settlement"
        building = BUILDING_NAMES.get(kind, str(kind).replace("Settlement_", "").replace("_", " "))
        out.append({"key": f"settlement.{str(s.get('UniqueId') or name).lower()}.{slot}"[:80].replace(" ", "-"),
                    "label": f"{name}: {building} built", "started_at": started, "ends_at": started + seconds,
                    "detail": f"Settlement construction (building {slot + 1}), {seconds // 60} min"})
    return out


def _event_seconds(expedition: dict, tables: dict) -> int:
    """5400 s per event, or the easy 900 s when the save's own times fit only that.

    The fleet moves 4 times per event (NumberOfUAChangesPerExpeditionEvent), so TimeOfLastUAChange - StartTime is
    a multiple of event/4: 1350 s normally, 225 s for easy expeditions. A multiple of 1350 is read as normal.
    """
    start, last = expedition.get("StartTime") or 0, expedition.get("TimeOfLastUAChange") or 0
    normal, easy = tables["event_seconds"], tables["event_seconds_easy"]
    if last > start:
        elapsed = last - start
        if elapsed % max(1, normal // 4) and not elapsed % max(1, easy // 4):
            return easy
    return normal


def expedition_timers(player_state: dict, tables: dict) -> list[dict]:
    """When each frigate expedition returns (paused ones are left out: their end is not known)."""
    out = []
    for i, e in enumerate(player_state.get("FleetExpeditions") or []):
        if not isinstance(e, dict) or not e.get("StartTime") or e.get("PauseTime"):
            continue
        events = len(e.get("Events") or [])
        if not events:
            continue
        step = _event_seconds(e, tables)
        start = int(e["StartTime"])
        done = max(0, min(events, int(e.get("NextEventToTrigger") or 0)))
        frigates = len(e.get("AllFrigateIndices") or [])
        category = (e.get("ExpeditionCategory") or {}).get("ExpeditionCategory") or "expedition"
        duration = (e.get("ExpeditionDuration") or {}).get("ExpeditionDuration") or ""
        seed = e.get("Seed")
        ident = (seed[1] if isinstance(seed, list) and len(seed) > 1 else str(i))
        next_event = (f"; next event {done + 1} of {events} at {clock(start + (done + 1) * step)}" if done < events else "")
        out.append({"key": f"expedition.{str(ident).lower().replace('0x', '')}"[:80],
                    "label": f"Frigate expedition returns ({frigates} frigate{'s' if frigates != 1 else ''})",
                    "started_at": start, "ends_at": start + events * step,
                    "detail": f"{category} {duration}".strip() + f", {events} events, {done} done{next_event}"})
    return out


def clock(epoch: float) -> str:
    """'13:21' in this computer's time zone (the player's)."""
    return datetime.fromtimestamp(epoch).strftime("%H:%M")


def timers_from_save(readable: dict, tables: dict) -> list[dict]:
    """Every timer of the save, soonest first (``visible`` drops the long-finished ones at view time)."""
    ps = ((readable or {}).get("BaseContext") or {}).get("PlayerStateData") or {}
    return sorted(settlement_timers(ps, tables) + expedition_timers(ps, tables), key=lambda t: t["ends_at"])


def visible(items: list[dict], now: float) -> list[dict]:
    """Running timers and those that ended within DONE_SHOWN_S."""
    return [t for t in items if t["ends_at"] > now - DONE_SHOWN_S]


EMPTY = ("No settlement construction or frigate expedition is running. New ones appear after the game's next "
         "save (it saves about once a minute while you play).")
INTRO = ("From your save: when settlement constructions and frigate expeditions finish (durations from the game's "
         "files). Press a bell to be notified when one ends - on this computer and on your phone.")


def timers_section(items: list[dict], section_types, now: float) -> dict:
    """The Overview's timers: a ``timers`` section (live countdown, notification bells; app 3.8.0) where the app
    renders one, else a table of end times."""
    shown = visible(items, now)
    if "timers" in (section_types or ()):
        return {"type": "timers", "id": "timers", "title": "Timers", "items": shown, "empty": EMPTY}
    rows = [[t["label"], clock(t["ends_at"]) + (" (done)" if t["ends_at"] <= now else ""), t.get("detail")] for t in shown]
    return {"type": "table", "id": "timers", "title": "Timers", "columns": ["What", "Ends", "Details"], "rows": rows,
            "empty": EMPTY}
