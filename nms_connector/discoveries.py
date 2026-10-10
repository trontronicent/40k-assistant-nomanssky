"""Your discoveries: what the save's discovery store holds (pure, no I/O) - plugin 0.15.0 "Discovery".

``DiscoveryManagerData.DiscoveryData-v1.Store.Record`` holds one record per thing a player scanned or named,
**including other players' records you came across**. The keys are the game's own short ones and are *not* in
``mapping.json``, so this is a hand-written reader (measured on the real save, 2026-10-10: 1,409 records):

``DD.DT`` kind (Mineral, Flora, Animal, SolarSystem, Sector, Planet, SpacePoi) - ``DD.UA`` the packed galactic
address (system and planet nibble) - ``DD.VP`` validation seeds - ``DM.CN`` the name a discoverer gave
(53 of 1,409; **none of the 262 animals**) - ``OWS`` the discoverer (``UID``, ``USN``, ``TS`` unix time) -
``FL`` flags - ``RID``.

* **Whose record is it?** The player's own id is the one every ``Sector`` and ``SpacePoi`` record carries (those
  are always the player's); ``own_uid`` takes the most common one among them.
* **Animal ``VP`` = [CreatureSeed, ?, SpeciesSeed, GenusSeed, CreatureSecondarySeed]** (4 or 5 entries): all 11
  pets in the same save matched their animal record on each of those indexes. Index 1 is unknown.
* **Flags are not interpreted.** ``FL.U`` appears on 190 records, *all* of them other players' - so it is no
  "uploaded by me" flag, and nothing here claims to know what ``C`` or ``F`` mean; they are shown as they are.
* There are no numeric totals to compare a planet's tally against (a planet record holds fauna/flora as
  description text), so there is **no completion percentage** - only what you have found.
"""

from __future__ import annotations

from collections import Counter

MAX_RECORDS = 20_000                 # a hand-edited or damaged save cannot grow the snapshot without bound
OWN_KINDS = ("Sector", "SpacePoi")   # records that are always the player's own
KIND_LABELS = {"SolarSystem": "System", "Planet": "Planet", "Animal": "Creature", "Flora": "Plant",
               "Mineral": "Mineral", "Sector": "Sector", "SpacePoi": "Space point"}
KIND_PLURALS = {"SolarSystem": "Systems", "Planet": "Planets", "Animal": "Creatures", "Flora": "Plants",
                "Mineral": "Minerals", "Sector": "Sectors", "SpacePoi": "Space points"}
KIND_ORDER = ("SolarSystem", "Planet", "Animal", "Flora", "Mineral", "SpacePoi", "Sector")
SCANNED_KINDS = ("Animal", "Flora", "Mineral")
PLANET_NIBBLE = 52


def _packed(value) -> int | None:
    """A packed address from the save: an int, or a '0x…' / decimal string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 16) if value.lower().startswith("0x") else int(value)
        except ValueError:
            return None
    return None


def _seed(value) -> int | None:
    """A validation seed: 0x… text or an int. Small numbers (the sector records' 512) are not seeds."""
    number = _packed(value)
    return number if number is not None and number > 0xFFFF else None


def own_uid(records: list) -> str | None:
    """The player's id: the most common ``OWS.UID`` among the records that are always theirs, else the most
    common one overall (a save with no sector records)."""
    def uid(record):
        return str(((record.get("OWS") or {}).get("UID")) or "")

    own = Counter(uid(r) for r in records if (r.get("DD") or {}).get("DT") in OWN_KINDS and uid(r))
    pool = own or Counter(uid(r) for r in records if uid(r))
    return pool.most_common(1)[0][0] if pool else None


def parse(records: list) -> list[dict]:
    """The records as compact, JSON-safe rows (what the snapshot keeps), bounded by ``MAX_RECORDS``.

    Row keys: ``k`` kind, ``a`` packed address (int), ``n`` the discoverer's name for it (or None), ``o`` the
    discoverer's user name, ``m`` whether it is the player's own record, ``t`` unix time (or None), ``f`` the raw
    flags (sorted list), ``s`` the validation seeds as ints. Records that are not objects or have no kind or no
    address are skipped; nothing is invented for them.
    """
    records = [r for r in (records or [])[:MAX_RECORDS] if isinstance(r, dict)]
    mine_uid = own_uid(records)
    rows = []
    for record in records:
        dd = record.get("DD") if isinstance(record.get("DD"), dict) else {}
        kind, address = dd.get("DT"), _packed(dd.get("UA"))
        if not isinstance(kind, str) or address is None:
            continue
        ows = record.get("OWS") if isinstance(record.get("OWS"), dict) else {}
        stamp = ows.get("TS")
        name = (record.get("DM") or {}).get("CN") if isinstance(record.get("DM"), dict) else None
        flags = record.get("FL") if isinstance(record.get("FL"), dict) else {}
        vp = dd.get("VP") if isinstance(dd.get("VP"), list) else []
        rows.append({
            "k": kind, "a": address, "n": name if isinstance(name, str) and name.strip() else None,
            "o": ows.get("USN") if isinstance(ows.get("USN"), str) else "",
            "m": bool(mine_uid) and str(ows.get("UID") or "") == mine_uid,
            "t": stamp if isinstance(stamp, int) and stamp > 0 else None,
            "f": sorted(str(k) for k, v in flags.items() if v),
            # Positions matter (0 creature, 2 species, 3 genus, 4 secondary), so an unusable entry stays a None
            # placeholder instead of shifting the ones after it.
            "s": [_seed(v) for v in vp[:5]] if kind == "Animal" else [],
        })
    return rows


def system_of(row: dict) -> int:
    """The system key of a row: its address without the planet nibble (one key per system)."""
    return row["a"] & ~(0xF << PLANET_NIBBLE)


def planet_of(row: dict) -> int:
    """The planet number 1-15 a row belongs to, 0 when it is about the system itself."""
    return (row["a"] >> PLANET_NIBBLE) & 0xF


class DiscoveryBook:
    """Questions about the parsed rows; built once per snapshot (cheap: one pass)."""

    def __init__(self, rows: list[dict] | None):
        self.rows = list(rows or [])
        self.mine = [r for r in self.rows if r["m"]]
        self.others = [r for r in self.rows if not r["m"]]

    def __bool__(self) -> bool:
        return bool(self.rows)

    def counts(self, rows: list[dict] | None = None) -> dict[str, int]:
        """{kind: records} in ``KIND_ORDER`` (kinds with none left out)."""
        tally = Counter(r["k"] for r in (self.rows if rows is None else rows))
        return {k: tally[k] for k in KIND_ORDER if tally.get(k)} | {k: n for k, n in sorted(tally.items())
                                                                     if k not in KIND_ORDER}

    def named(self) -> list[dict]:
        """Records somebody gave a name, newest first (ties by name, so the order never depends on the save)."""
        return sorted((r for r in self.rows if r["n"]), key=lambda r: (-(r["t"] or 0), r["n"], r["a"]))

    def by_system(self, mine_only: bool = True) -> list[dict]:
        """{system, planets, plants, creatures, minerals, total, named} per system, most discoveries first."""
        systems: dict[int, Counter] = {}
        for r in (self.mine if mine_only else self.rows):
            tally = systems.setdefault(system_of(r), Counter())
            tally[r["k"]] += 1
            tally["named"] += 1 if r["n"] else 0
            if r["k"] in SCANNED_KINDS:
                tally["scanned"] += 1
        out = [{"system": key, "planets": t["Planet"], "plants": t["Flora"], "creatures": t["Animal"],
                "minerals": t["Mineral"], "scanned": t["scanned"], "named": t["named"],
                "total": sum(v for k, v in t.items() if k in KIND_LABELS)} for key, t in systems.items()]
        return sorted(out, key=lambda e: (-e["scanned"], -e["total"], e["system"]))

    def animal_by_seed(self) -> dict[int, dict]:
        """{CreatureSeed: the animal record} - the join to a companion (VP index 0). The player's own record
        wins when two records share a seed, then the oldest."""
        found: dict[int, dict] = {}
        for r in sorted((r for r in self.rows if r["k"] == "Animal" and r["s"] and r["s"][0] is not None),
                        key=lambda r: (not r["m"], r["t"] or 0, r["a"])):
            found.setdefault(r["s"][0], r)
        return found

    def first_seen(self) -> int | None:
        """When the oldest record of the player's was made (unix time), or None."""
        stamps = [r["t"] for r in self.mine if r["t"]]
        return min(stamps) if stamps else None


def matches(book: DiscoveryBook, terms: list[str], kinds: set[str], limit: int = 12) -> list[dict]:
    """The **named** rows whose name contains every term (folded by the caller), restricted to ``kinds`` when given;
    the player's own first, then the most recently made. A row without a name has nothing to show or to match, and
    taking the best ``limit`` rows *before* dropping the unnamed ones hid every named planet behind unnamed ones
    (seen on the real save: 73 planets, 20 named, and the first 12 by date were all unnamed)."""
    out = []
    for r in book.rows:
        if not r["n"] or (kinds and r["k"] not in kinds):
            continue
        name = (r["n"] or "").casefold()
        if terms and not all(t in name for t in terms):
            continue
        out.append(r)
    out.sort(key=lambda r: (not r["m"], -(r["t"] or 0), r["n"] or "", r["a"]))
    return out[:limit]
