"""Exact galactic positions of the systems you visit, read from the running game.

The save and the system address only name a *region* (voxel X, Y, Z), so distances between systems were measured
between regions. The game itself knows where your system lies inside its region: a render parameter named
``gGalacticScale`` (a NUL-terminated name, its value 0x20 bytes after the name's start) holds the current
system's position divided by 100, in voxel units. Read 2026-10-05 in Yibrazh, region (-384, 2, -1755):
(-3.837331, 0.020779, -17.541409) -> (-383.733, 2.078, -1754.141) = the region plus (0.27, 0.08, 0.86) of a
voxel; stable over half a minute in the system. Only the *current* system's position is there, so positions are
collected as you travel (history.positions) and every distance between two recorded systems becomes exact.

**It is the galaxy map's camera focus** (seen 2026-10-05 with the map open: it moved to (-383.487, 2.326,
-1754.320) while you stayed in Yibrazh). With the map closed it sits on the current system. So a value is recorded
for the current system only when it can be its own: inside that system's region (each axis between the region's
voxel and the next), unchanged since you arrived in the system and for at least SETTLE_S (the value of the system
you left may linger during a warp; a value that moved means the map was open and the camera wandered - that
system is then not recorded until the next arrival), and different from every position recorded for another
system (a stale value is refused).
"""

from __future__ import annotations

import math
import struct

GALACTIC_NAME = b"gGalacticScale\x00\x00"     # 16 bytes as stored (name, NUL, padding)
GALACTIC_VALUE_AT = 0x20
GALACTIC_UNIT = 100.0
SETTLE_S = 30
SEARCH_EVERY_S = 120
SAME_EPS = 1e-4                               # positions this close are the same reading


def parse_value(raw: bytes | None) -> tuple[float, float, float] | None:
    """Voxel position from the 12 value bytes; None when they are not a usable position."""
    if not raw or len(raw) < 12:
        return None
    vals = struct.unpack("<3f", raw[:12])
    if not all(math.isfinite(v) for v in vals) or all(v == 0 for v in vals) or any(abs(v) > 30 for v in vals):
        return None
    return tuple(round(v * GALACTIC_UNIT, 4) for v in vals)


def inside_region(pos: tuple[float, float, float], region: tuple[int, int, int]) -> bool:
    return all(0 <= p - r < 1 for p, r in zip(pos, region))


class PositionTracker:
    """Finds the parameter once (and again when it stops making sense), reads 12 bytes per tick, and says
    when a reading may be recorded for the current system."""

    def __init__(self, chunker=None, finder=None):
        from . import memory
        self._chunks = chunker or memory.chunks
        self._find = finder or memory.find_aligned
        self.address: int | None = None
        self._searched_at: float | None = None
        self._system: int | None = None
        self._since: float = 0.0
        self._first: tuple[float, float, float] | None = None   # the first reading since arriving
        self._moved = False                                      # the value changed since arriving (map open)
        self.last: tuple[float, float, float] | None = None

    def _search(self, reader, now: float) -> None:
        self._searched_at = now
        self.address = None
        for _base, address, buf, valid, length in self._chunks(reader, 64):
            for at in self._find(buf, GALACTIC_NAME, valid, length, address, align=8):
                if parse_value(reader.read(address + at + GALACTIC_VALUE_AT, 12)) is not None:
                    self.address = address + at + GALACTIC_VALUE_AT
                    return

    def tick(self, reader, system_key: int | None, region: tuple[int, int, int] | None, now: float):
        """(system key, position) to record, or None (not settled, not found, outside the region)."""
        if system_key is None or region is None:
            self._system = None
            return None
        if system_key != self._system:
            self._system, self._since, self._first, self._moved = system_key, now, None, False
        value = parse_value(reader.read(self.address, 12)) if self.address is not None else None
        if value is None and (self._searched_at is None or now - self._searched_at >= SEARCH_EVERY_S):
            self._search(reader, now)
            value = parse_value(reader.read(self.address, 12)) if self.address is not None else None
        self.last = value
        if value is not None:
            if self._first is None:
                self._first = value
            elif value != self._first:
                self._moved = True
        if value is None or self._moved or now - self._since < SETTLE_S or not inside_region(value, region):
            return None
        return system_key, value


def accept(positions: dict[int, tuple], key: int, pos: tuple) -> bool:
    """May `pos` be stored for system `key`? Not when another system already has this very reading (stale)."""
    return not any(k != key and all(abs(a - b) < SAME_EPS for a, b in zip(p, pos)) for k, p in positions.items())
