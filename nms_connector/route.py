"""Route planning between systems (pure).

A warp costs one jump (one warp cell) whatever its length, as long as it is
within the hyperdrive's range. So the best route has the fewest jumps; among
those the one with the fewest jumps into *unknown* space (known systems are
stops you can find on the galaxy map), then the shortest distance. A detour
can never save jumps over flying straight (each leg rounds up), so known
systems are used exactly when they cost no extra jump. Known systems (visited, discovered,
recorded) are stepping stones; where none is in range, a leg crosses unknown
space in several jumps - every system on the way is a possible stop, the game
just has not shown it to you yet - and the route says which region to aim for
on each of those jumps.

Distances come from regions (galaxy.distance_ly: ~400 ly per voxel step,
0 inside one region); the real distance between two systems can differ by up
to a region's size, so plan with some margin on the range.
"""

from __future__ import annotations

import heapq
import math
import re

from . import galaxy

PORTAL_RE = re.compile(r"^[0-9A-Fa-f]{12}$")


def portal_to_key(code: str, galaxy_index: int) -> int | None:
    """A 12-glyph portal address as hex (P SSS YY ZZZ XXX) -> the system key in `galaxy_index`, or None."""
    code = (code or "").strip().replace(" ", "").replace("-", "")
    if not PORTAL_RE.match(code):
        return None
    system, y, z, x = int(code[1:4], 16), int(code[4:6], 16), int(code[6:9], 16), int(code[9:12], 16)
    return x | z << 12 | y << 24 | (galaxy_index & 0xFF) << 32 | system << 40


def jumps_for(distance: float | None, range_ly: float) -> int | None:
    """Jumps needed for a distance with a hyperdrive range (at least one; None across galaxies)."""
    if distance is None:
        return None
    return max(1, math.ceil(distance / range_ly - 1e-9))


def _waypoints(a: int, b: int, jumps: int) -> list[tuple[int, int, int]]:
    """Regions to aim for on the jumps between a and b (evenly spaced on the straight line)."""
    (ax, ay, az), (bx, by, bz) = galaxy.region(a), galaxy.region(b)
    return [(round(ax + (bx - ax) * k / jumps), round(ay + (by - ay) * k / jumps), round(az + (bz - az) * k / jumps))
            for k in range(1, jumps)]


def plan_route(nodes, origin: int, target: int, range_ly: float) -> dict:
    """The route with the fewest jumps from origin to target, via known systems in `nodes`.

    Returns {ok, reason?, legs: [{from, to, distance, jumps, waypoints}], jumps, distance, direct_jumps,
    direct_distance}. A leg with more than one jump crosses unknown space (waypoints = regions to aim for).
    """
    if range_ly is None or not range_ly > 0:
        return {"ok": False, "reason": "the jump range must be a positive number of light years"}
    if origin == target:
        return {"ok": False, "reason": "you are already in that system"}
    direct = galaxy.distance_ly(origin, target)
    if direct is None:
        return {"ok": False, "reason": "the target is in another galaxy - routes stay inside one galaxy"}
    here = galaxy.galaxy_of(origin)
    stops = sorted({k for k in nodes if galaxy.galaxy_of(k) == here} | {origin, target})
    worst = (math.inf, math.inf, math.inf)
    best = {origin: (0, 0, 0.0)}
    previous: dict[int, int] = {}
    queue = [(0, 0, 0.0, origin)]
    while queue:
        jumps, unknown, dist, node = heapq.heappop(queue)
        if node == target:
            break
        if (jumps, unknown, dist) > best.get(node, worst):
            continue
        for nxt in stops:
            if nxt == node:
                continue
            d = galaxy.distance_ly(node, nxt)
            j = jumps_for(d, range_ly)
            cost = (jumps + j, unknown + j - 1, dist + d)
            if cost < best.get(nxt, worst):
                best[nxt] = cost
                previous[nxt] = node
                heapq.heappush(queue, (*cost, nxt))
    path = [target]
    while path[-1] != origin:
        path.append(previous[path[-1]])
    path.reverse()
    legs = []
    for a, b in zip(path, path[1:], strict=False):
        d = galaxy.distance_ly(a, b)
        j = jumps_for(d, range_ly)
        legs.append({"from": a, "to": b, "distance": d, "jumps": j, "waypoints": _waypoints(a, b, j)})
    return {"ok": True, "legs": legs, "jumps": sum(leg["jumps"] for leg in legs),
            "unknown_jumps": sum(leg["jumps"] - 1 for leg in legs),
            "distance": sum(leg["distance"] for leg in legs), "direct_jumps": jumps_for(direct, range_ly),
            "direct_distance": direct, "range": range_ly}
