"""Where systems are in the galaxy, how far apart, and the nearest planet with a resource (pure).

A packed system address names a *region* (voxel X, Y, Z: a cube of the galaxy,
X and Z -2048..2047, Y -128..127) and a system index inside it. The save gives no
finer position. PROTOTYPE: star positions found on the galaxy map (positions.py,
star fixes named by the user) are set with ``set_positions``; two systems that both
have one are measured as the map does - floor(distance x REGION_LY), verified on 4
stars on 2026-10-05 - and marked (ExactLy). For the others:

- distances are measured between regions, at REGION_LY light years per voxel
  step (the community's figure for the galaxy map; approximate), and two
  systems in one region are "in the same region" (closer than about 400 ly);
- on the map, systems of one region are spread on a small circle around the
  region's point by their system index, so they do not cover each other. The
  spread is for display only and never enters a distance.

Distances are only defined inside one galaxy (RealityIndex).
"""

from __future__ import annotations

import math

REGION_LY = 400
GALAXY_BOUNDS = {"min": [-2048, -128, -2048], "max": [2047, 127, 2047]}
SPREAD = 0.42          # voxel radius of the display circle for the systems of one region
GOLDEN_ANGLE = math.pi * (3 - math.sqrt(5))

_positions: dict[int, tuple] = {}     # system key -> exact voxel position (set_positions)


class ExactLy(float):
    """A distance between two star positions read on the galaxy map (PROTOTYPE): shown as exact."""


def set_positions(positions: dict[int, tuple]) -> None:
    """The exact positions known (named star fixes, history.positions); distances and the map use them."""
    global _positions
    _positions = positions


def exact(key: int) -> tuple[float, float, float] | None:
    """The system's exact voxel position, if a star fix was named for it (PROTOTYPE)."""
    return _positions.get(key & ~(0xF << 52)) if key is not None else None


def _signed(value: int, bits: int) -> int:
    return value - (1 << bits) if value >= (1 << (bits - 1)) else value


def region(key: int) -> tuple[int, int, int]:
    """(X, Y, Z) voxel of a packed address."""
    return (_signed(key & 0xFFF, 12), _signed((key >> 24) & 0xFF, 8), _signed((key >> 12) & 0xFFF, 12))


def galaxy_of(key: int) -> int:
    return (key >> 32) & 0xFF


def system_index(key: int) -> int:
    return (key >> 40) & 0xFFF


def map_position(key: int) -> tuple[float, float, float]:
    """Display position: the exact one when known, else the region's voxel plus a small, stable offset by
    system index."""
    known = exact(key)
    if known:
        return known
    x, y, z = region(key)
    index = system_index(key)
    angle = index * GOLDEN_ANGLE
    radius = SPREAD * (0.35 + 0.65 * ((index * 2654435761) % 1000) / 1000)
    return (x + radius * math.cos(angle), float(y), z + radius * math.sin(angle))


def distance_ly(a: int, b: int) -> float | None:
    """Distance between two systems in light years: exact (ExactLy, the map's floor) when both have a star
    position, else between their regions (0 in one region); None across galaxies."""
    if galaxy_of(a) != galaxy_of(b):
        return None
    pa, pb = exact(a), exact(b)
    if pa and pb:
        return ExactLy(math.floor(REGION_LY * math.dist(pa, pb)))
    (ax, ay, az), (bx, by, bz) = region(a), region(b)
    return REGION_LY * math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)


def distance_text(ly: float | None, same_system: bool = False) -> str:
    if same_system:
        return "this system"
    if ly is None:
        return "other galaxy"
    if isinstance(ly, ExactLy):
        return f"{ly:,.0f} ly (exact, prototype)"
    if ly == 0:
        return "same region (< 400 ly)"
    return f"~{ly:,.0f} ly"


def planet_resources(planet: dict, gas: str | None = None) -> list[str]:
    """Every resource a planet offers: the three substances, the plant resources and the harvester gas."""
    ids = [planet.get("common"), planet.get("uncommon"), planet.get("rare")] + list(planet.get("extra") or []) + [gas]
    return list(dict.fromkeys(i for i in ids if i))


def nearest_by_resource(systems: dict[int, list[dict]], origin: int | None, gas_of) -> list[dict]:
    """For every resource on a recorded planet: the nearest planet offering it, seen from `origin`.

    `systems` maps system keys to recorded planets, `gas_of(planet)` gives a planet's harvester gas.
    Without an origin, or for planets in another galaxy, the distance is unknown and such planets only win
    when nothing nearer offers the resource. The origin system itself always wins (regions are coarse:
    many systems share one, at distance 0); then distance, more planets offering it there, name.
    Returns [{resource, system, planet, distance, count}] sorted by resource id.
    """
    best: dict[str, dict] = {}
    for key, planets in systems.items():
        dist = distance_ly(origin, key) if origin is not None else None
        offered: dict[str, int] = {}
        for planet in planets:
            for res in planet_resources(planet, gas_of(planet)):
                offered[res] = offered.get(res, 0) + 1
        for planet in planets:
            for res in planet_resources(planet, gas_of(planet)):
                rank = (dist is None, key != origin, dist if dist is not None else 0.0, -offered[res],
                        planet.get("name") or "")
                if res not in best or rank < best[res]["rank"]:
                    best[res] = {"resource": res, "system": key, "planet": planet, "distance": dist,
                                 "count": offered[res], "rank": rank}
    return [{k: v for k, v in e.items() if k != "rank"} for _, e in sorted(best.items())]
