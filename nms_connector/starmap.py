"""The galaxy map's star records in the game's memory, traced back to their systems - and predictions for the rest.

With the galaxy map open (and the Economy Scanner installed) the game holds a GcGalaxyStarAttributesData record
(economy, wealth, conflict, race, star colour, planet count; memory.parse_star_attributes) for many stars around
you - 41 systems on 2026-10-05, all within two regions. A record has no address, only its planets' seeds; the
game derives those seeds from the system's address (procgen.planet_seeds, exact). So ``seed_table`` lists the
first planet's seed of every system in the regions around you, and ``find_records`` looks those seeds up in
memory: one pass, each hit checked against the record's values and its second planet's seed.

Checked 2026-10-05 against systems visited before: Delta Sol, Kayana XIV, Kayanis Majoris VIII and Ulebsk read the
same from the map's records as on the visit. Every other known system gets procgen's prediction instead (marked
``predicted``; 17 of 17 recorded systems predicted right).
"""

from __future__ import annotations

import time

from . import procgen

REGION_RADIUS = 1                 # regions around yours whose systems are looked for (27 regions, ~29,000 systems)
LOW_BITS = 24                     # pre-filter on the seeds' low 24 bits: ~0.2 % of memory words pass


def neighbourhood(center: int, radius: int = REGION_RADIUS) -> list[int]:
    """Packed keys (planet 0) of every system index in the regions within `radius` of `center`'s region."""
    x, z, y, galaxy = center & 0xFFF, (center >> 12) & 0xFFF, (center >> 24) & 0xFF, (center >> 32) & 0xFF
    keys = []
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                base = ((x + dx) & 0xFFF) | ((z + dz) & 0xFFF) << 12 | ((y + dy) & 0xFF) << 24 | galaxy << 32
                keys += [base | idx << 40 for idx in range(1, procgen.MAX_SYSTEM_INDEX + 1)]
    return keys


class SeedTable:
    """The planet seeds of a set of systems, as numpy arrays sorted by the first planet's seed: ``first``, the system
    ``keys`` and the second planet's seed (``second``, 0 = the system has one body). The scan needs nothing else
    of a system. As a dict of tuples holding a list of Python ints per system, the ~29,000 systems of 27 regions held
    ~12 MB for as long as the game ran; as arrays they take under 1 MB. An empty table is falsy."""

    def __init__(self, first, keys, second):
        self.first, self.keys, self.second = first, keys, second

    def __len__(self) -> int:
        return len(self.first)

    @classmethod
    def from_rows(cls, rows: dict[int, tuple[int, int]]) -> SeedTable:
        """From {first seed: (system key, second seed or 0)}."""
        import numpy as np
        order = sorted(rows)
        return cls(np.array(order, np.uint64), np.array([rows[s][0] for s in order], np.uint64),
                   np.array([rows[s][1] for s in order], np.uint64))


def seed_table(keys: list[int]) -> SeedTable:
    """The SeedTable of the given systems (one pass of procgen over them, ~0.9 s for 29,000)."""
    rows: dict[int, tuple[int, int]] = {}
    for key in keys:
        seeds = procgen.planet_seeds(key)
        if seeds:
            rows[seeds[0]] = (key, seeds[1] if len(seeds) > 1 else 0)
    return SeedTable.from_rows(rows)


def _as_table(table) -> SeedTable:
    """A SeedTable from either form: the dict {first seed: (key, all seeds)} older code and tests build is converted."""
    if isinstance(table, SeedTable):
        return table
    return SeedTable.from_rows({s: (key, seeds[1] if len(seeds) > 1 else 0) for s, (key, seeds) in (table or {}).items()})


def find_records(reader, table: dict, chunker=None) -> dict[int, dict]:
    """{system key: star attributes} of the star records in memory whose planets are a listed system's."""
    import numpy as np

    from . import memory
    chunker = chunker or memory.chunks
    table = _as_table(table)
    if not len(table):
        return {}
    seeds = table.first
    low = np.zeros(1 << LOW_BITS, bool)      # 16 MB, freed with this call
    low[(seeds & np.uint64((1 << LOW_BITS) - 1)).astype(np.intp)] = True
    found: dict[int, dict] = {}
    for _base, address, buf, valid, _length in chunker(reader, 0):
        count = valid - valid % 8
        if count < 8:
            continue
        words = np.frombuffer(buf, np.uint64, count // 8)
        cand = np.flatnonzero(low[(words & np.uint64((1 << LOW_BITS) - 1)).astype(np.intp)])
        if not len(cand):
            continue
        vals = words[cand]
        pos = np.searchsorted(seeds, vals)
        pos[pos >= len(seeds)] = 0
        hit = seeds[pos] == vals
        for i, p in zip(cand[hit].tolist(), pos[hit].tolist(), strict=True):
            key = int(table.keys[p])
            if key in found:
                continue
            start = i * 8 - memory.STAR_PLANET_SEEDS
            blob = bytes(buf[start:start + memory.STAR_SIZE]) if start >= 0 and start + memory.STAR_SIZE <= valid \
                else reader.read(address + start, memory.STAR_SIZE)
            attrs = memory.parse_star_attributes(blob) if blob else None
            if not attrs:
                continue
            if table.second[p]:     # a second planet's seed must sit in its slot too
                second = int.from_bytes(blob[memory.STAR_PLANET_SEEDS + 0x10:memory.STAR_PLANET_SEEDS + 0x18], "little")
                if second != int(table.second[p]):
                    continue
            found[key] = attrs
    return found


class StarmapReader:
    """Reads the map's star records around the current system every SCAN_EVERY_S (seed table cached per region)."""

    SCAN_EVERY_S = 180

    def __init__(self, chunker=None, clock=time.time):
        self._chunker = chunker
        self._clock = clock
        self._table_for: int | None = None
        self._table: SeedTable | None = None
        self.last_scan_at: float | None = None
        self.last_scan_seconds: float | None = None
        self.last_found = 0

    def release(self) -> None:
        """Forget the seed table (rebuilt for the region at the next scan)."""
        self._table, self._table_for = None, None

    def due(self, now: float) -> bool:
        return self.last_scan_at is None or now - self.last_scan_at >= self.SCAN_EVERY_S

    def scan(self, reader, current: int) -> dict[int, dict]:
        """Read the galaxy map's star records around the current system (the seed table is built per region)."""
        started = time.perf_counter()
        region = current & 0xFFFFFFFFFF          # the region + galaxy, no system index
        if region != self._table_for:
            self._table = seed_table(neighbourhood(current))
            self._table_for = region
        found = find_records(reader, self._table, self._chunker)
        self.last_scan_at = self._clock()
        self.last_scan_seconds = round(time.perf_counter() - started, 1)
        self.last_found = len(found)
        return found


_predictions: dict[int, dict] = {}


def clear_predictions() -> None:
    """Forget the predicted economies (recomputed on demand)."""
    _predictions.clear()

MAX_PREDICTIONS = 5000        # a map of a few hundred systems is shown at a time; never let this grow without bound


def predicted(key: int) -> dict:
    """procgen's attributes for a system (cached), marked ``predicted``."""
    key = key & ~(0xF << 52)
    if key not in _predictions:
        if len(_predictions) >= MAX_PREDICTIONS:
            _predictions.clear()
        a = procgen.system_attributes(key)
        # A pirate system shows conflict "Pirate" in the game (0x079 next to Yibrazh, read 2026-10-05); upstream
        # reports the flag only.
        _predictions[key] = {"economy": a["economy"], "wealth": a["wealth"],
                             "conflict": "Pirate" if a["pirate"] else a["conflict"],
                             "race": a["race"], "star": a["star"], "pirate": a["pirate"], "abandoned": a["abandoned"],
                             "uncharted": a["uncharted"], "predicted": True}
    return _predictions[key]
