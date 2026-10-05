"""PROTOTYPE - exact star positions from the galaxy map's camera, read from the running game (read-only).

The save and the system address only name a *region* (voxel X, Y, Z), so distances between systems are measured
between regions ("same region, < 400 ly" for two systems of one region). The galaxy map knows better, and this
module reads it - **as a prototype**: the method is verified on few samples and identifying the star is manual.

What was found on 2026-10-05 (research/galaxy_distances.json in this repository):

* A render parameter block of the galaxy map holds ``gTracePDX``, ``gTracePDY`` and ``gGalacticScale`` (NUL-terminated
  names, each value 0x20 after its name; the names 0x60 apart: PDX at gGalacticScale - 0x240, PDY at - 0x1E0).
* ``gGalacticScale`` is the map camera's **eye** position / 100, in region units (one unit = 400 LJ: for every
  locked star the map's "distance to the heart" = |eye| x 400 to 1 LJ). It is *not* a star: with the map closed it
  keeps the camera's last eye. (Until 0.10.0 the plugin recorded it as the current system's position - wrong;
  those values are kept in the history file as ``positions_discarded`` and no longer used.)
* ``gTracePDX`` / ``gTracePDY`` are the screen's right and down half-axes (|PDX| / |PDY| = the screen aspect,
  perpendicular), so the camera looks along ``normalize(cross(PDX, PDY))``.
* A locked star sits at the screen centre: it is on the line eye + t * forward. Two locks of one star from
  different directions meet at the star (misses 0.0-0.2 LJ in all 5 stars tried), and the map's star-to-star
  distance is ``floor(|a - b| x 400)`` LJ (157.6 -> 157, 109.4 -> 109, 116.5 -> 116, 56.0 -> 56 from Delta Sol).

``CameraReader`` finds the block once and reads 0x260 bytes per sample; ``StarFixer`` keeps the rays of settled
camera views and turns two rays that meet (closer than MAX_MISS_LY, at least MIN_ANGLE_DEG apart) into a **star
fix**. Which system a fix is cannot be read reliably yet (the map's label record kept an old address), so the user
names fixes on the page; a named fix makes that system's distances exact (marked prototype).
"""

from __future__ import annotations

import math
import struct
import time

GALACTIC_NAME = b"gGalacticScale\x00\x00"     # 16 bytes as stored (name, NUL, padding)
PDX_NAME, PDY_NAME = b"gTracePDX\x00", b"gTracePDY\x00"
GALACTIC_VALUE_AT = 0x20                      # a value sits 0x20 after its name
PDX_FROM_EYE, PDY_FROM_EYE = -0x240, -0x1E0   # from gGalacticScale's value to the other two values
BLOCK = 0x260                                 # PDX value .. eye value + 12, read in one go
GALACTIC_UNIT = 100.0                         # the stored eye is position / 100
REGION_LY = 400.0
SEARCH_EVERY_S = 120
SETTLED_SAMPLES = 3                           # eye unchanged for 3 samples (2 s) = a settled lock. With 2 (1 s), samples
                                              # of the camera still easing in made 7 false fixes in a replay of 2026-10-05's
                                              # log; with 3 exactly the 5 real stars came out, each within 0.12 LJ
MAX_MISS_LY = 0.5                             # two rays of one star meet closer than this (measured: 0.0-0.2 LJ)
MIN_ANGLE_DEG = 5.0                           # nearly parallel rays meet anywhere: not a fix
SAME_STAR_LY = 3.0                            # a fix within this of an existing one is the same star (neighbours: >= 19 LJ seen)
CONFIRMED_RAYS = 3                            # 2 lines of sight can cross by chance (settled non-lock views): 3 confirm
UNCONFIRMED_AGE_S = 86400                     # unnamed fixes with 2 lines of sight are dropped after a day
MAX_RAYS = 40                                 # recent settled rays kept for pairing
RAY_AGE_S = 900
MAX_LINES = 12                                # lines of sight kept per fix
FORGET = "forget"                            # the naming form's option to drop a fix


def parse_value(raw: bytes | None) -> tuple[float, float, float] | None:
    """The eye position (region units) from the 12 value bytes; None when they are not a usable position."""
    if not raw or len(raw) < 12:
        return None
    vals = struct.unpack("<3f", raw[:12])
    if not all(math.isfinite(v) for v in vals) or all(v == 0 for v in vals) or any(abs(v) > 30 for v in vals):
        return None
    return tuple(round(v * GALACTIC_UNIT, 5) for v in vals)


def _norm(v):
    length = math.sqrt(sum(c * c for c in v))
    return tuple(c / length for c in v) if length > 1e-9 else None


def forward_of(pdx, pdy) -> tuple[float, float, float] | None:
    """The viewing direction: perpendicular to the screen's two half-axes; None when they are degenerate."""
    cross = (pdx[1] * pdy[2] - pdx[2] * pdy[1], pdx[2] * pdy[0] - pdx[0] * pdy[2], pdx[0] * pdy[1] - pdx[1] * pdy[0])
    return _norm(cross)


def closest_point(eye_a, dir_a, eye_b, dir_b) -> tuple[tuple[float, float, float], float, float] | None:
    """Where two rays (lines) come closest: (midpoint, miss distance in region units, angle in degrees); None for
    parallel lines."""
    w = [a - b for a, b in zip(eye_a, eye_b)]
    b = sum(x * y for x, y in zip(dir_a, dir_b))
    d = sum(x * y for x, y in zip(dir_a, w))
    e = sum(x * y for x, y in zip(dir_b, w))
    denom = 1 - b * b
    if denom < 1e-9:
        return None
    s, t = (b * e - d) / denom, (e - b * d) / denom
    pa = [p + s * q for p, q in zip(eye_a, dir_a)]
    pb = [p + t * q for p, q in zip(eye_b, dir_b)]
    angle = math.degrees(math.acos(max(-1.0, min(1.0, abs(b)))))
    return tuple(round((x + y) / 2, 5) for x, y in zip(pa, pb)), math.dist(pa, pb), angle


def map_distance_ly(a, b) -> int:
    """The galaxy map's distance between two star positions: floor(|a - b| x 400) LJ (verified on 4 stars)."""
    return math.floor(math.dist(a, b) * REGION_LY)


class CameraReader:
    """Reads the galaxy map camera: eye position and viewing direction. Finds the parameter block once (again at
    most every SEARCH_EVERY_S when it stops making sense) and checks the two axis names before trusting it."""

    def __init__(self, chunker=None, finder=None):
        from . import memory
        self._chunks = chunker or memory.chunks
        self._find = finder or memory.find_aligned
        self.eye_at: int | None = None
        self._searched_at: float | None = None

    def _search(self, reader, now: float) -> None:
        self._searched_at = now
        self.eye_at = None
        for _base, address, buf, valid, length in self._chunks(reader, 64):
            for at in self._find(buf, GALACTIC_NAME, valid, length, address, align=8):
                name = address + at
                pdx = reader.read(name + PDX_FROM_EYE, len(PDX_NAME))
                pdy = reader.read(name + PDY_FROM_EYE, len(PDY_NAME))
                if pdx == PDX_NAME and pdy == PDY_NAME:
                    self.eye_at = name + GALACTIC_VALUE_AT
                    return

    def read(self, reader, now: float) -> dict | None:
        """{eye, forward} now, or None (block not found, unreadable or not a camera)."""
        sample = self._sample(reader)
        if sample is None and (self._searched_at is None or now - self._searched_at >= SEARCH_EVERY_S):
            self._search(reader, now)
            sample = self._sample(reader)
        return sample

    def _sample(self, reader) -> dict | None:
        if self.eye_at is None:
            return None
        raw = reader.read(self.eye_at + PDX_FROM_EYE, BLOCK)
        if not raw or len(raw) < BLOCK:
            return None
        eye = parse_value(raw[-0x20:-0x14])
        forward = forward_of(struct.unpack_from("<3f", raw, 0), struct.unpack_from("<3f", raw, 0x60))
        return {"eye": eye, "forward": forward} if eye and forward else None


class StarFixer:
    """Turns settled camera views into star fixes: two settled rays that meet are a star's position."""

    def __init__(self, fixes: list[dict] | None = None, clock=time.time):
        self.fixes: list[dict] = fixes if fixes is not None else []
        self.rays: list[dict] = []
        self._clock = clock
        self._last_eye = None
        self._still = 0
        self._last_ray_eye = None

    def feed(self, sample: dict | None) -> list[dict]:
        """One camera sample; returns the fixes it created or refined."""
        if sample is None:
            self._last_eye, self._still = None, 0
            return []
        eye = sample["eye"]
        self._still = self._still + 1 if eye == self._last_eye else 1
        self._last_eye = eye
        if self._still != SETTLED_SAMPLES or eye == self._last_ray_eye:
            return []
        self._last_ray_eye = eye
        now = self._clock()
        ray = {"eye": eye, "forward": sample["forward"], "at": now}
        self.rays = [r for r in self.rays if now - r["at"] <= RAY_AGE_S][-(MAX_RAYS - 1):]
        changed = []
        for other in self.rays:
            met = closest_point(ray["eye"], ray["forward"], other["eye"], other["forward"])
            if met is None:
                continue
            point, miss, angle = met
            if miss * REGION_LY <= MAX_MISS_LY and angle >= MIN_ANGLE_DEG:
                fix = self._merge(point, (ray, other), now)
                if fix not in changed:
                    changed.append(fix)
        self.rays.append(ray)
        self._expire(now)
        return changed

    def _expire(self, now: float) -> None:
        """Drop unnamed fixes that only two lines of sight ever met at and that were not seen for a day: in a replay
        of 2026-10-05's camera log, settled views that were no locks crossed by chance a few times."""
        def keep(fix):
            if fix.get("system") or fix["rays"] >= CONFIRMED_RAYS:
                return True
            try:
                seen = time.mktime(time.strptime(fix["last_seen"], "%Y-%m-%dT%H:%M:%S"))
            except (KeyError, TypeError, ValueError):
                return True
            return now - seen <= UNCONFIRMED_AGE_S
        self.fixes[:] = [f for f in self.fixes if keep(f)]

    def _merge(self, point, rays, now: float) -> dict:
        """Add two meeting lines of sight to the fix of that star (within SAME_STAR_LY) or start one; the fix's
        position is the best intersection of all its lines (least squares), so one slightly-off line cannot pull
        it the way averaging crossing points did (1.4 LJ in a replay of real data)."""
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))
        fix = next((f for f in self.fixes if math.dist(f["position"], point) * REGION_LY <= SAME_STAR_LY), None)
        if fix is None:
            fix = {"id": max((f["id"] for f in self.fixes), default=0) + 1, "position": list(point), "rays": 0,
                   "miss_ly": 0.0, "first_seen": stamp, "last_seen": stamp, "system": None, "lines": []}
            self.fixes.append(fix)
        lines = fix.setdefault("lines", [])
        for ray in rays:
            line = [list(ray["eye"]), [round(c, 6) for c in ray["forward"]]]
            if line not in lines:
                lines.append(line)
        del lines[:-MAX_LINES]
        solved = intersect(lines)
        # A line that misses the common point by more than one star's lines do belongs to another star: drop the
        # worst until all agree (keeps at least two).
        while solved is not None and solved[1] * REGION_LY > MAX_MISS_LY and len(lines) > 2:
            del lines[solved[2]]
            solved = intersect(lines)
        if solved is not None:
            fix["position"], miss = solved[0], solved[1]
            fix["miss_ly"] = round(miss * REGION_LY, 2)
        fix["rays"] = len(lines)
        fix["last_seen"] = stamp
        return fix



def intersect(lines) -> tuple[list[float], float, int] | None:
    """(the point closest to all lines [[eye, forward], ...] (least squares), the largest miss in region units, the
    index of the line that misses most); None when they are (nearly) parallel."""
    a = [[0.0] * 3 for _ in range(3)]
    b = [0.0] * 3
    for eye, f in lines:
        for i in range(3):
            for j in range(3):
                m = (1.0 if i == j else 0.0) - f[i] * f[j]
                a[i][j] += m
                b[i] += m * eye[j]
    det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
           + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    if abs(det) < 1e-12:
        return None
    def solve(col):
        m = [row[:] for row in a]
        for i in range(3):
            m[i][col] = b[i]
        return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])) / det
    x = [solve(0), solve(1), solve(2)]
    misses = []
    for eye, f in lines:
        d = [x[i] - eye[i] for i in range(3)]
        along = sum(d[i] * f[i] for i in range(3))
        misses.append(math.sqrt(max(0.0, sum(c * c for c in d) - along * along)))
    worst = max(range(len(misses)), key=misses.__getitem__)
    return [round(c, 5) for c in x], misses[worst], worst


def named_positions(fixes: list[dict]) -> dict[int, tuple]:
    """{system key: position} of the fixes the user named (galaxy.set_positions)."""
    return {int(f["system"], 16): tuple(f["position"]) for f in fixes if f.get("system")}
