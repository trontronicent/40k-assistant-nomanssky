"""Your settlements' economy from the save: population, the eight settlement stats, production and perks.

The save (``SettlementStatesV2``, one entry per settlement; yours are those you own) stores per settlement:

- ``Stats``: int[8], indexed by GcSettlementStatType (STATS below). They are the values the game keeps, not the
  bars it draws: it scales each between ``StatsMinValues`` and ``StatsMaxValues`` of GcSettlementGlobals, and
  ``NormalisedStatBadThresholds`` / ``NormalisedStatGoodThresholds`` mark the bad and good zones of that scale.
  Read 2026-10-04 for Kay City: [0, 36, 84308, -3250, 0, 931025, 338, 552]; Debt fell to 927557 eleven minutes
  later (it changes while you play). They are not the bars of the settlement screen one to one: Population
  capacity is stored as 0, so the game adds its buildings' and perks' effects when it draws them. The tab
  therefore shows the stored values and where they sit on the game's scale, without a good/bad verdict.
- ``Population``, ``Race``, ``Perks`` (ids such as ``^POL_PROD#27032``: perk id + a seed for procedural ones),
  ``PendingJudgementType`` (a decision waiting for you) and ``LastJudgementTime``.
- ``ProductionState``: the products the settlement makes (``ElementId``, ``Amount`` made by
  ``LastChangeTimestamp``, ``ProductionAccumulationCap``).

**What the settlement screen shows** is computed by the game (stored values + buildings + perks) and found only
in its memory (``LiveSettlements``): the settlement's seed (u64, 8-aligned), two ints (1, 0), then the eight
computed stats - only while the settlement's screen is open. (A first reading had the seed twice in a row; the
second copy was a coincidence, absent at the next opening.) Verified 2026-10-04 against the screen: [52, 41, 489454, 395010, 0, 908027, 358,
552] = population 20 / 52 (max.), happiness 34 % ((41 + 30) / 210 on the -30..180 scale), productivity
489,454 units/day, maintenance 395,010 units/day, sentinel alert 36 % (358 / 1000). The save alone had
[0, 36, 84308, -3250, 0, 913425, 358, 552].

From the game's files (``load_tables``): the stat ranges and thresholds, the wait between decisions
(``JudgementWaitTimeMin``/``Max``: 900 and 7200 s - the game draws the actual wait in between, so only the
window is known) and the perk table (``settlementperkstable.mbin``: name/description keys, negative or not,
which stats a perk moves and how strongly). Offsets: libMBIN 7.04 plus the 0x20-byte MBIN header, checked
against the installed game (build 25625620) on 2026-10-04; values that make no sense fall back to FALLBACK.
"""

from __future__ import annotations

import json
import re
import struct
import time
from pathlib import Path

from . import mbin
from .timers import BUILDING_NAMES, MBIN_HEADER, SETTLEMENT_FILE, clock, player_uid

PERKS_FILE = "metadata/reality/tables/settlementperkstable.mbin"
PERKS_PAK = "NMSARC.MetadataEtc.pak"

# GcSettlementStatType.SettlementStatTypeEnum, in order, with the names the game's settlement screen uses.
STATS = ["MaxPopulation", "Happiness", "Production", "Upkeep", "Sentinels", "Debt", "Alert", "BugAttack"]
STAT_LABELS = {"MaxPopulation": "Population capacity", "Happiness": "Happiness", "Production": "Productivity",
               "Upkeep": "Maintenance", "Sentinels": "Sentinel threat", "Debt": "Debt", "Alert": "Sentinel alert",
               "BugAttack": "Bug attack"}
# GcSettlementStatStrength.SettlementStatStrengthEnum, in order. Positive/negative means better/worse for you,
# not up/down: STARTING_NEG9 has Upkeep NegativeMedium and the game describes it as "Increases maintenance costs".
STRENGTHS = ["varies", "large", "medium", "small", "small", "medium", "large"]
NEGATIVE_FROM = 4                              # NegativeSmall and below make the stat worse

# GcSettlementGlobals offsets (libMBIN 7.04, without the header).
STATS_MAX_AT = 0xB3D0                          # int[8] StatsMaxValues
STATS_MIN_AT = 0xB3F0                          # int[8] StatsMinValues
BAD_AT = 0xB370                                # float[8] NormalisedStatBadThresholds
GOOD_AT = 0xB390                               # float[8] NormalisedStatGoodThresholds
JUDGEMENT_WAIT_AT = 0xB430                     # int JudgementWaitTimeMax, int JudgementWaitTimeMin
MAX_NPC_AT = 0xB440                            # int MaxNPCPopulation

# GcSettlementPerkData (libMBIN 7.04): record 0x78 bytes.
PERK_RECORD = 0x78
PERK_DESC_AT, PERK_NAME_AT, PERK_ID_AT, PERK_CHANGES_AT, PERK_FLAGS_AT = 0x00, 0x20, 0x50, 0x60, 0x70
PERK_ID_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,15}$")

# Measured from the game's files on 2026-10-04 (build 25625620): used when they cannot be read.
FALLBACK = {
    "stats_min": [0, -30, 0, 0, 0, 0, 0, 0],
    "stats_max": [175, 180, 1500000, 1000000, 100, 10000000, 1000, 1000],
    "bad": [0.15, 0.2, 0.3, 0.2, 0.2, 0.5, 0.5, 0.5],
    "good": [0.6, 0.7, 0.7, 0.7, 0.6, 0.5, 0.5, 0.5],
    "judgement_wait": [900, 7200], "max_npcs": 30, "perks": {}, "source": "built-in (measured 2026-10-04)",
}


def parse_globals(settlement: bytes) -> dict | None:
    """Stat ranges, thresholds, the decision wait and the NPC cap from GcSettlementGlobals; None when they make no
    sense (a game update moved the fields)."""
    h = MBIN_HEADER
    try:
        smax = list(struct.unpack_from("<8i", settlement, h + STATS_MAX_AT))
        smin = list(struct.unpack_from("<8i", settlement, h + STATS_MIN_AT))
        bad = [round(v, 3) for v in struct.unpack_from("<8f", settlement, h + BAD_AT)]
        good = [round(v, 3) for v in struct.unpack_from("<8f", settlement, h + GOOD_AT)]
        wait_max, wait_min = struct.unpack_from("<2i", settlement, h + JUDGEMENT_WAIT_AT)
        npcs = struct.unpack_from("<i", settlement, h + MAX_NPC_AT)[0]
    except struct.error:
        return None
    if (not all(lo < hi for lo, hi in zip(smin, smax)) or not all(0 <= v <= 1 for v in bad + good)
            or not 60 <= wait_min <= wait_max <= 7 * 86400 or not 1 <= npcs <= 1000):
        return None
    return {"stats_min": smin, "stats_max": smax, "bad": bad, "good": good,
            "judgement_wait": [wait_min, wait_max], "max_npcs": npcs}


def parse_perks(data: bytes) -> dict[str, dict]:
    """settlementperkstable.mbin -> {perk id: {name, description, negative, job, blessing, procedural, starter,
    changes}}; {} when the layout is not the expected one. ``changes`` is [(stat, "better (large)")]."""
    try:
        start, count = mbin.root_list(data)
        if mbin.record_size(data, start, count) != PERK_RECORD:
            return {}
        out = {}
        for k in range(count):
            p = start + k * PERK_RECORD
            perk_id = mbin.fixed_str(data, p + PERK_ID_AT, 0x10)
            if not perk_id or not PERK_ID_RE.match(perk_id):
                continue
            offset, n = struct.unpack_from("<QI", data, p + PERK_CHANGES_AT)
            changes = []
            for j in range(min(n, 16)):
                stat, strength = struct.unpack_from("<II", data, p + PERK_CHANGES_AT + offset + j * 0xC)
                if stat < len(STATS) and strength < len(STRENGTHS):
                    word = "worse" if strength >= NEGATIVE_FROM else "better"
                    changes.append((STATS[stat], f"{word} ({STRENGTHS[strength]})"))
            blessing, job, negative, proc, starter = data[p + PERK_FLAGS_AT:p + PERK_FLAGS_AT + 5]
            out[perk_id] = {"name": mbin.fixed_str(data, p + PERK_NAME_AT, 0x20),
                            "description": mbin.fixed_str(data, p + PERK_DESC_AT, 0x20),
                            "negative": bool(negative), "job": bool(job), "blessing": bool(blessing),
                            "procedural": bool(proc), "starter": bool(starter), "changes": changes}
    except (struct.error, mbin.MbinError, IndexError):
        return {}
    # Sanity: a shifted read yields no ids, or ids without name keys.
    named = sum(1 for p in out.values() if (p["name"] or "").startswith("UI_"))
    return out if out and named >= len(out) * 0.8 else {}


def load_tables(install) -> dict:
    """The settlement tables of the installed game, else FALLBACK (``source`` says which, ``error`` why)."""
    from .hgpak import PakError, PakSet, ZstdUnavailable
    if install is None:
        return dict(FALLBACK, error="game installation not found")
    try:
        with PakSet(install.pcbanks, {SETTLEMENT_FILE: PERKS_PAK, PERKS_FILE: PERKS_PAK}) as paks:
            stats = parse_globals(paks.read(SETTLEMENT_FILE))
            perks = parse_perks(paks.read(PERKS_FILE))
    except (KeyError, OSError, PakError, ZstdUnavailable) as exc:
        return dict(FALLBACK, error=f"{type(exc).__name__}: {exc}")
    errors = [what for what, ok in (("settlement globals", stats), ("perk table", perks)) if not ok]
    out = dict(FALLBACK, **(stats or {}), perks=perks, source="game files" if not errors else FALLBACK["source"])
    if errors:
        out["error"] = f"the game's {' and '.join(errors)} changed layout (a game update?)"
    return out


LIVE_STATS_AFTER = 0x10          # the computed stats follow the settlement's seed (8 bytes) and two ints
LIVE_SIZE = LIVE_STATS_AFTER + 8 * 4
SEARCH_EVERY_S = 15              # memory search (~0.75 s) for a settlement in your system whose screen is not found


def seed_needle(seed: int) -> bytes:
    """The bytes in front of a settlement's computed stats: its seed (u64, 8-aligned)."""
    return struct.pack("<Q", seed)


def parse_live(raw: bytes | None, seed: int) -> list[int] | None:
    """The eight computed stats from LIVE_SIZE bytes read at the seed; None when they are not that record (the
    seed is in memory ~150 times; only the stats' ranges tell this record apart)."""
    if not raw or len(raw) < LIVE_SIZE or raw[:8] != seed_needle(seed):
        return None
    # Between seed and stats: (1, 0) in both readings of 2026-10-04. A look-alike with the seed in front of eight
    # small in-range ints ([41, 41, 41, 41, 50, 39, 39, 39], ints 36 and 46) passed the range check alone.
    marker, zero = struct.unpack_from("<2i", raw, 8)
    stats = list(struct.unpack_from("<8i", raw, LIVE_STATS_AFTER))
    capacity, happiness, production, upkeep, sentinels, debt, alert, bugs = stats
    if not (0 <= marker <= 16 and zero == 0 and 1 <= capacity <= 1000 and -1000 <= happiness <= 1000
            and 0 <= production < 10 ** 9 and 0 <= upkeep < 10 ** 9 and 0 <= sentinels <= 1000
            and 0 <= debt < 10 ** 9 and 0 <= alert <= 100000 and 0 <= bugs <= 100000):
        return None
    return stats


class LiveSettlements:
    """The settlement screen's values from the running game, per settlement seed (read-only).

    ``tick`` re-reads known records (48 bytes each) and, for settlements in the system you are in (``nearby``),
    searches memory for the others at most once per SEARCH_EVERY_S. The game builds the record only while the
    settlement's screen is open (2026-10-04: on the settlement's planet with the screen closed it was absent), so
    the search runs often there and nowhere else; ``values`` keeps the last good reading per seed with its time,
    and ``path`` (the plugin's data folder) keeps it across restarts.
    """

    def __init__(self, path: Path | None = None, chunker=None, clock=time.time):
        from . import memory
        self._chunks = chunker or memory.chunks
        self._clock = clock
        self.path = path
        self.load_error: str | None = None
        self.addresses: dict[int, int] = {}
        self.values: dict[int, dict] = self._load()
        self._searched_at: float | None = None
        self.last_search_seconds: float | None = None

    def _load(self) -> dict[int, dict]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8")) if self.path else {}
            return {int(k, 16): {"stats": [int(v) for v in e["stats"]][:8], "at": float(e["at"])} for k, e in raw.items()
                    if len(e.get("stats") or []) == 8}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
            # A damaged file only loses the last readings; the next visit writes it again.
            self.load_error = f"{type(exc).__name__}: {exc}"
            return {}

    def _save(self) -> None:
        if not self.path:
            return
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({f"{k:x}": v for k, v in self.values.items()}), encoding="utf-8")
        tmp.replace(self.path)

    def tick(self, reader, seeds: list[int], nearby: list[int] | None = None) -> None:
        """Re-read the known records of `seeds`; search for the missing ones of `nearby` (default: all)."""
        before = {k: v["stats"] for k, v in self.values.items()}
        try:
            self._tick(reader, seeds, seeds if nearby is None else nearby)
        finally:
            if {k: v["stats"] for k, v in self.values.items()} != before:
                self._save()

    def _tick(self, reader, seeds: list[int], nearby: list[int]) -> None:
        now = self._clock()
        for seed in seeds:
            address = self.addresses.get(seed)
            stats = parse_live(reader.read(address, LIVE_SIZE), seed) if address is not None else None
            if stats is None:
                self.addresses.pop(seed, None)
            else:
                self.values[seed] = {"stats": stats, "at": now}
        missing = [s for s in nearby if s not in self.addresses]
        if missing and (self._searched_at is None or now - self._searched_at >= SEARCH_EVERY_S):
            self._search(reader, missing, now)

    def _search(self, reader, seeds: list[int], now: float) -> None:
        started = time.perf_counter()
        self._searched_at = now
        import numpy as np
        wanted = np.array(seeds, dtype=np.uint64)
        found: dict[int, int] = {}
        for _base, address, buf, valid, length in self._chunks(reader, LIVE_SIZE):
            words = np.frombuffer(buf, np.uint64, valid // 8)       # chunks are page-aligned: words are 8-aligned
            for i in np.flatnonzero(np.isin(words, wanted)):
                at = int(i) * 8
                seed = int(words[i])
                if at >= length or seed in found:
                    continue
                raw = bytes(buf[at:at + LIVE_SIZE]) if at + LIVE_SIZE <= valid else reader.read(address + at, LIVE_SIZE)
                if parse_live(raw, seed) is not None:
                    found[seed] = address + at
            if len(found) == len(seeds):
                break
        for seed, address in found.items():
            self.addresses[seed] = address
            self.values[seed] = {"stats": parse_live(reader.read(address, LIVE_SIZE), seed) or self.values.get(seed, {}).get("stats"),
                                 "at": now}
        self.last_search_seconds = round(time.perf_counter() - started, 2)


def _enum(value, field: str) -> str | None:
    return (value or {}).get(field) if isinstance(value, dict) else None


def perk_id(raw: str | None) -> str:
    """'^POL_PROD#27032' -> 'POL_PROD' (the table's id; the number seeds a procedural perk's details)."""
    return str(raw or "").lstrip("^").split("#", 1)[0]


def settlements_from_save(readable: dict) -> list[dict]:
    """Your settlements (owned by the save's player), as plain values for the Settlements tab."""
    ps = ((readable or {}).get("BaseContext") or {}).get("PlayerStateData") or {}
    uid = player_uid(ps)
    out = []
    for s in ps.get("SettlementStatesV2") or []:
        if not isinstance(s, dict) or not uid or ((s.get("Owner") or {}).get("UID")) != uid:
            continue
        stats = s.get("Stats") or []
        production = []
        for slot in s.get("ProductionState") or []:
            element = str((slot or {}).get("ElementId") or "").lstrip("^")
            if element:
                production.append({"item": element, "amount": int(slot.get("Amount") or 0),
                                   "cap": int(slot.get("ProductionAccumulationCap") or 0),
                                   "at": int(slot.get("LastChangeTimestamp") or 0)})
        building = _enum(s.get("NextBuildingUpgradeClass"), "BuildingClass")
        try:
            seed = int(str(s.get("SeedValue") or "0"), 16) if isinstance(s.get("SeedValue"), str) else int(s.get("SeedValue") or 0)
        except ValueError:
            seed = 0
        ua = s.get("UniverseAddress")
        out.append({
            "name": s.get("Name") or "Settlement",
            "seed": seed,
            "system": (ua & ~(0xF << 52)) if isinstance(ua, int) else None,     # memory.system_key
            "race": _enum(s.get("Race"), "AlienRace"),
            "population": int(s.get("Population") or 0),
            "stats": [int(v) for v in stats[:len(STATS)]] if len(stats) >= len(STATS) else [],
            "production": production,
            "perks": [p for p in (s.get("Perks") or []) if p],
            "pending": _enum(s.get("PendingJudgementType"), "SettlementJudgementType"),
            "last_judgement": int(s.get("LastJudgementTime") or 0),
            "building": None if building in (None, "None") else BUILDING_NAMES.get(building, building),
        })
    return out


def text_keys(items: list[dict], tables: dict) -> set[str]:
    """The localisation keys the tab shows (perk names and descriptions)."""
    keys = set()
    for s in items:
        for raw in s["perks"]:
            perk = tables["perks"].get(perk_id(raw)) or {}
            keys.update(k for k in (perk.get("name"), perk.get("description")) if k)
    return keys


def item_ids(items: list[dict]) -> list[str]:
    return list(dict.fromkeys(p["item"] for s in items for p in s["production"]))


def level(stat: str, value: int, tables: dict) -> int:
    """Where a stored value sits on the game's scale for that stat, in percent (clamped to 0..100)."""
    i = STATS.index(stat)
    lo, hi = tables["stats_min"][i], tables["stats_max"][i]
    return round(min(1.0, max(0.0, (value - lo) / (hi - lo))) * 100) if hi > lo else 0


def _words(enum_name: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", enum_name).capitalize()


def _fmt(value: int) -> str:
    return f"{value:,}".replace(",", "'")


EMPTY = "You have no settlement in this save. Settlements you run appear here after the game's next save."


# How the settlement screen writes each stat: "count" (population), "percent" of the game's scale, "per day".
SHOWN_AS = {"MaxPopulation": "count", "Happiness": "percent", "Production": "per day", "Upkeep": "per day",
            "Sentinels": "percent", "Debt": "count", "Alert": "percent", "BugAttack": "percent"}


def shown(stat: str, value: int, tables: dict, population: int | None = None) -> str:
    """A computed stat the way the settlement screen writes it (20 / 52, 34 %, 489'454 units/day)."""
    how = SHOWN_AS[stat]
    if stat == "MaxPopulation" and population is not None:
        return f"{population} / {value}"
    if how == "percent":
        return f"{level(stat, value, tables)} %"
    if how == "per day":
        return f"{_fmt(value)} units/day"
    return _fmt(value)


def settlement_sections(items: list[dict], tables: dict, texts, now: float, live: dict | None = None) -> list[dict]:
    """The Settlements tab: one block per settlement (status, stats, production, perks). ``live``: seed ->
    {stats, at} from LiveSettlements (the settlement screen's values)."""
    if not items:
        return [{"type": "text", "text": EMPTY}]
    live = live or {}
    out: list[dict] = [{"type": "text", "text":
        "Stats as the settlement screen shows them are read from the running game (they include your buildings "
        "and perks); without the game, only what the save stores is known, which differs. Everything else comes "
        "from your save (updated when the game saves)."}]
    wait_min, wait_max = tables["judgement_wait"]
    for s in items:
        name = s["name"]
        if s["pending"] and s["pending"] != "None":
            decision = f"waiting for you ({_words(s['pending'])})"
        elif s["last_judgement"]:
            start, end = s["last_judgement"] + wait_min, s["last_judgement"] + wait_max
            decision = ("any time now" if end <= now else
                        f"between {clock(start)} and {clock(end)}" if start > now else f"by {clock(end)} at the latest")
            decision += f" (last one {clock(s['last_judgement'])}; the game waits {wait_min // 60} min to {wait_max // 3600} h)"
        else:
            decision = "unknown"
        out.append({"type": "kv", "title": name, "items": [
            {"label": "Population", "value": f"{s['population']} (the game allows up to {tables['max_npcs']} residents)"},
            {"label": "Race", "value": _words(s["race"]) if s["race"] else "unknown"},
            {"label": "Next decision", "value": decision},
            {"label": "Construction", "value": s["building"] or "none in progress"},
        ]})
        reading = live.get(s.get("seed"))
        if s["stats"] or reading:
            game = reading["stats"] if reading else [None] * len(STATS)
            stored = s["stats"] or [None] * len(STATS)
            rows = []
            for i, stat in enumerate(STATS):
                rows.append([STAT_LABELS[stat],
                             shown(stat, game[i], tables, s["population"]) if game[i] is not None else None,
                             _fmt(stored[i]) if stored[i] is not None else None,
                             f"{_fmt(tables['stats_min'][i])} to {_fmt(tables['stats_max'][i])}"])
            when = (f"in the game ({'now' if now - reading['at'] < 120 else 'at ' + clock(reading['at'])})" if reading
                    else "in the game (read when you visit the settlement)")
            out.append({"type": "table", "title": f"{name}: stats", "columns": ["Stat", when.capitalize(), "Stored in the save",
                                                                               "Game's range"], "rows": rows})
        if s["production"]:
            out.append({"type": "table", "title": f"{name}: production",
                        "columns": ["Product", "Ready at last visit", "Holds up to", "Last collected or updated"],
                        "rows": [[texts.item(p["item"]), _fmt(p["amount"]), _fmt(p["cap"]), clock(p["at"]) if p["at"] else "-"]
                                 for p in s["production"]]})
        perk_rows = []
        for raw in s["perks"]:
            perk = tables["perks"].get(perk_id(raw))
            if not perk:
                perk_rows.append([perk_id(raw), "", "", ""])
                continue
            effect = ", ".join(f"{STAT_LABELS[stat]} {change}" for stat, change in perk["changes"])
            kind = "negative" if perk["negative"] else "job" if perk["job"] else "blessing" if perk["blessing"] else "positive"
            desc = texts.key(perk["description"])
            desc = desc if desc != perk["description"] else None
            label = texts.key(perk["name"]) or perk_id(raw)
            if "%" in label:     # procedural ("%PROD_ADJ% %PROD%"): the game builds the name from the perk's seed
                label = f"{desc or perk_id(raw)} (named in the game)"
                desc = None
            origin = "founding" if perk["starter"] else "a decision" if perk["procedural"] else "an event"
            perk_rows.append([{"text": label, "hint": desc} if desc else label, kind, effect, origin])
        if perk_rows:
            out.append({"type": "table", "title": f"{name}: perks", "columns": ["Perk", "Kind", "Effect", "From"],
                        "rows": perk_rows})
    if tables.get("error"):
        out.append({"type": "text", "text": f"Stat ranges: built-in values ({tables['error']})."})
    return out
