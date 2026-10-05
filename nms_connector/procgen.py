"""The game's procedural generation of star systems, from a system's address (pure).

Ported from hadsh/nms_namegen (https://github.com/hadsh/nms_namegen), MIT licensed:
Copyright (c) 2026 Stuart Coyle & had.sh & GGF. Permission is hereby granted, free of charge, to any person
obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute,
sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions: The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

Only the parts this plugin uses are ported (system attributes and planet seeds; no name generation), without
numpy. What it gives, for any system address:

- ``planet_seeds``: the GenerationData.Seed of every body - exactly the game's (checked 2026-10-05: Yibrazh's six
  and Delta Sol's five recorded seeds). That is how a GcGalaxyStarAttributesData record in the game's memory
  (which has no address, only its planets' seeds) is traced back to its system - see starmap.py.
- ``system_attributes``: star colour, planet counts and the predicted economy, wealth, conflict and race. These
  predictions are upstream's (94.8 % economy, 97.8 % wealth, 97.3 % conflict, 99.1 % race on community-recorded
  systems), so the plugin shows them as *predicted* and prefers what it read from the game.

Addresses here are packed keys as the plugin uses them (memory.pack_address: X | Z << 12 | Y << 24 |
galaxy << 32 | system << 40); ``portal_code`` converts.
"""

from __future__ import annotations

import math
import struct

MASK64 = 0xFFFFFFFFFFFFFFFF
MULTIPLIER = 0x5A76F899
CONST_A = 0x64DD81482CBD31D7
CONST_B = 0xE36AA5C613612997

ABANDONED_SYSTEM_THRESHOLD = [0.0, 0.10000000149011612, 0.10000000149011612, 0.0, 0.3499999940395355]
EMPTY_SYSTEM_THRESHOLD = [0.0, 0.4000000059604645, 0.4000000059604645, 0.949999988079071, 0.20000000298023224]
PIRATE_SYSTEM_THRESHOLD = [0.25, 0.15000000596046448, 0.15000000596046448, 0.5, 0.05000000074505806]
# upstream's categories -> the game's names (memory.TRADING_CLASSES etc.)
ECONOMIES = {1: "Trading", 2: "Fusion", 3: "Scientific", 4: "Mining", 5: "Manufacturing", 6: "HighTech",
             7: "PowerGeneration"}
WEALTHS = {1: "Poor", 2: "Average", 3: "Wealthy"}
CONFLICTS = {1: "Low", 2: "Default", 3: "High"}
RACES = {0: "None", 1: "Gek", 2: "Korvax", 3: "Vy'keen"}
STAR_TYPES = ["Yellow", "Green", "Blue", "Red", "Purple"]
MAX_SYSTEM_INDEX = 0x42F          # purple systems go up to 0x429


class PRNG:
    """The game's 64-bit multiply-with-carry random generator (nms_namegen's port)."""
    def __init__(self, seed: int):
        self.seed = seed

    def update(self) -> None:
        self.seed = ((self.seed & 0xFFFFFFFF) * MULTIPLIER) + (self.seed >> 32)

    def random(self, n: int) -> int:
        self.update()
        return ((self.seed & 0xFFFFFFFF) * n) >> 32

    def randi(self) -> int:
        self.update()
        return self.seed & 0xFFFFFFFF


def _probability(word: int) -> float:
    """A 32-bit draw as the game compares it: a float32 in [0, 1)."""
    return struct.unpack("<f", struct.pack("<f", (word & 0xFFFFFFFF) / 4294967296.0))[0]


def _ror64(x: int, r: int) -> int:
    r &= 63
    return ((x >> r) | (x << (64 - r))) & MASK64


def _round(a, b, c, d, rota, rotb):
    a1 = (_ror64(b, rota) ^ c) & MASK64
    b1 = (_ror64(a, rotb) ^ d) & MASK64
    return a1, b1, (b1 + c) & MASK64, (a1 + d) & MASK64


def _hash(a, b, c, d, key, seed):
    """The Threefish-style mixing rounds the game uses to derive per-system seeds (four 64-bit words)."""
    a, b, c, d = _round(a, b, c, d, -0x17, 0x18)
    a, b, c, d = _round(a, b, c, d, -0x5, 0x1B)
    a = (a + key + 1) & MASK64
    d = (d + key + 1) & MASK64
    a, b, c, d = _round(a, b, c, d, -0x19, 0x1F)
    a, b, c, d = _round(a, b, c, d, 0x12, -0xC)
    a, b, c, d = _round(a, b, c, d, 0x6, -0x16)
    a, b, c, d = _round(a, b, c, d, -0x20, -0x20)
    a = (a + seed + 2) & MASK64
    d = (d + key + seed + 2) & MASK64
    a, b, c, d = _round(a, b, c, d, -0xE, -0x10)
    a, b, c, d = _round(b, a, d, c, 0x7, 0xC)
    a, b, c, d = _round(b, a, d, c, -0x17, 0x18)
    a, b, c, d = _round(a, b, c, d, -0x5, 0x1B)
    a = (a + 3) & MASK64
    b = (b + key) & MASK64
    c = (c + key) & MASK64
    d = (d + 3 + seed) & MASK64
    a, b, c, d = _round(a, b, c, d, -0x19, 0x1F)
    a, b, c, d = _round(a, b, c, d, 0x12, -0xC)
    a, b, c, d = _round(a, b, c, d, 0x6, -0x16)
    a, b, c, d = _round(a, b, c, d, -0x20, -0x20)
    a = (a + 4) & MASK64
    b = (b + seed) & MASK64
    c = (c + seed + key) & MASK64
    d = (d + 4) & MASK64
    a, b, c, d = _round(a, b, c, d, -0xE, -0x10)
    a, b, c, d = _round(a, b, c, d, 0xC, 0x7)
    a, b, c, d = _round(a, b, c, d, -0x17, 0x18)
    return [(c + seed) & MASK64, _ror64(a, 0x1B) ^ d, d, ((_ror64(b, -0x5) ^ c) + 5) & MASK64]


def _index_primed(ua: int) -> int:
    """The primed generation seed of a system from its packed universe address."""
    seed = ua & 0xFFFFFFFFFF
    system_id = ((ua >> 0x20) >> 8) & 0xFFF
    key = (seed ^ 0x1BD11BDAA9FC1A22) & MASK64
    b = _ror64(seed, 7) ^ seed
    o = _hash(seed, b, b + seed, seed + seed, key, seed)
    if system_id >= 9:
        index = system_id - 1
        counter = (index - 8) & 7
        a = ((index - 8) >> 3) + 1 + seed
        b = _ror64(a, 7) ^ a
        o = _hash(a, b, b + a, a + a, key, seed)
    else:
        counter = system_id - 1
    slot = counter >> 1
    counter += 1
    return (o[slot] >> 0x20) & MASK64 if not (counter & 1) else o[slot] & MASK64


def portal_code(key: int) -> tuple[int, int]:
    """(portal code 0xPSSSYYZZZXXX without the planet, galaxy) of a packed system key."""
    x, z, y = key & 0xFFF, (key >> 12) & 0xFFF, (key >> 24) & 0xFF
    galaxy, system = (key >> 32) & 0xFF, (key >> 40) & 0xFFF
    return (system << 32) | (y << 24) | (z << 12) | x, galaxy


def voxel_attributes(code: int) -> dict:
    """Per-region counts the generation uses, from the region's packed voxel code (distance from the core)."""
    x, y, z = code & 0xFFF, (code & 0xFF000000) >> 24, (code & 0xFFF000) >> 12
    x = x - 0x1000 if x > 0x7FF else x
    z = z - 0x1000 if z > 0x7FF else z
    y = y - 0x100 if y > 0x7F else y
    out = {"guide_star_count": 0x78, "black_hole_count": 1, "atlas_station_count": 1, "renegade": 0}
    distance = int(math.sqrt(x * x + y * y + z * z))
    if distance < 8:
        out.update(guide_star_count=0, black_hole_count=0, atlas_station_count=0)
    if 8 < distance < 1440:
        diff = max(0, min(0x78, int((distance - 8) * 120 / 1440)))
        out["renegade"] = 0x78 - diff
    return out


def system_attributes(key: int) -> dict:
    """Star colour, planet counts and the predicted economy, wealth, conflict and race of a system."""
    code, galaxy = portal_code(key)
    code &= 0xFFFFFFFFFFF
    system_id = (code & 0xFFF00000000) >> 32
    ua = (((system_id << 8) | (galaxy & 0xFF)) << 32) | (code & 0xFFFFFFFF)
    va = voxel_attributes(code)
    system_id -= 1
    system_seed = _index_primed(ua) & 0xFFFFFFFF
    rol16 = (((system_seed & 0x0000FFFF) << 16) | ((system_seed & 0xFFFF0000) >> 16)) ^ system_seed
    rol16 &= 0xFFFFFFFF
    seed = ((system_seed + 1) if system_seed == 0 else system_seed) * MULTIPLIER + rol16
    rng = PRNG(seed)
    star_type, safe_start, prime, anomaly = 0, 0, 2, 0
    if system_id < va["guide_star_count"]:
        planet_count = (((seed & 0xFFFFFFFF) * 4) >> 0x20) + 3
        safe_start = rng.random(planet_count) + 1
    else:
        if (((seed & 0xFFFFFFFF) * 0x64) >> 0x20) < 0x1E:
            star_type = rng.random(3) + 1
        diff = system_id - va["guide_star_count"]
        if va["black_hole_count"] > 0 and 0 <= diff < va["black_hole_count"]:
            anomaly, star_type = 2, 0
        if (va["atlas_station_count"] > 0 and diff - va["black_hole_count"] >= 0
                and diff - va["black_hole_count"] < va["atlas_station_count"]):
            anomaly, star_type = 1, 0
        planet_count = rng.random(6) + 1
        safe_start = 0 if (va["renegade"] >= 10 or star_type != 0 or anomaly != 0) else rng.random(planet_count + 1)
    rng.update()
    economy = {0: 4, 1: 6, 2: 1, 3: 5, 4: 2, 5: 3, 6: 7}[((rng.seed & 0xFFFFFFFF) * 7) >> 32]
    rng.update()
    pct = ((rng.seed & 0xFFFFFFFF) * 100) >> 32
    wealth = {0: 3, 1: 1, 2: 2}[0 if pct < 10 else (1 if pct < 30 else 2)]
    rng.update()
    conflict = {0: 1, 1: 2, 2: 3}[((rng.seed & 0xFFFFFFFF) * 3) >> 32]
    rng.update()
    race = {0: 1, 1: 3, 2: 2}[((rng.seed & 0xFFFFFFFF) * 3) >> 32]
    if system_id < va["renegade"]:
        star_type = rng.random(3) + 1
    if 0x3E7 < system_id < 0x429:
        star_type = 4
    rng.update()
    abandoned = _probability(rng.seed) < ABANDONED_SYSTEM_THRESHOLD[star_type]
    uncharted = False
    if not abandoned:
        rng.update()
        uncharted = _probability(rng.seed) < EMPTY_SYSTEM_THRESHOLD[star_type]
    if uncharted:
        race = 0
    if abandoned:
        wealth, conflict = 1, 1
    left = 6 - planet_count
    if left < 1:
        prime = 0
    elif rng.random(100) >= 33 or left < 2:
        prime = 1
    gas_giant = False
    if star_type == 4:
        prime += planet_count
        planet_count = 0
        if rng.random(100) < 15:
            gas_giant = True
            if rng.random(100) < 66:
                planet_count, prime = 0, 6
    pirate = False
    if not abandoned and not uncharted and (star_type != 0 or safe_start <= 0):
        peek = PRNG(rng.seed)
        peek.update()
        pirate = _probability(peek.seed) < PIRATE_SYSTEM_THRESHOLD[star_type]
    return {"planet_count": planet_count, "prime_planet_count": prime, "safe_start_planet": safe_start,
            "gas_giant": gas_giant, "star": STAR_TYPES[star_type], "economy": ECONOMIES[economy],
            "wealth": WEALTHS[wealth], "conflict": CONFLICTS[conflict], "race": RACES[race],
            "uncharted": uncharted, "abandoned": abandoned, "pirate": pirate, "anomaly": anomaly}


def _body_seed(rng: PRNG) -> int:
    low = rng.randi()
    high = rng.randi()
    r = (high << 0x20) | low
    r = (((r >> 33) ^ r) * CONST_A) & MASK64
    r = (((r >> 33) ^ r) * CONST_B) & MASK64
    return (r >> 33) ^ r


def planet_seeds(key: int, attrs: dict | None = None) -> list[int]:
    """The GenerationData.Seed of every body of the system, in the game's order (= planet index)."""
    attrs = attrs or system_attributes(key)
    code, galaxy = portal_code(key)
    coords = code & 0xFFFFFFFF
    index = ((code & 0x0FFF00000000) >> 24) | galaxy
    r = (index << 0x20) | coords
    r = (((r >> 33) ^ r) * CONST_A) & MASK64
    r = (((r >> 33) ^ r) * CONST_B) & MASK64
    r = (r >> 33) ^ r
    seed_h = ((((r & 0xFFFF0000) >> 16) | ((r & 0x0000FFFF) << 16)) ^ (r & 0xFFFFFFFF) ^ (r >> 32)) or 1
    rng = PRNG((seed_h << 32) | (r & 0xFFFFFFFF))
    primary = attrs["planet_count"]
    total = primary + attrs["prime_planet_count"]
    stop = attrs["safe_start_planet"] - 1
    seeds: list[int] = []
    if attrs["gas_giant"]:
        return [_body_seed(rng) for _ in range(total)]
    i = 0
    while i < primary:
        i += 1
        if rng.random(3) == 0:
            moons = rng.random(max(0, min(2, primary - i)) + 1)
            if moons > 0:
                while i != stop:
                    i += 1
                    moons -= 1
                    if moons <= 0:
                        break
    i = 0
    while i < primary:
        seeds.append(_body_seed(rng))
        i += 1
    while i < total:
        size = rng.random(3)
        seeds.append(_body_seed(rng))
        i += 1
        if size == 0:
            moons = rng.random(max(0, min(2, total - i)) + 1)
            while moons > 0 and i != stop:
                seeds.append(_body_seed(rng))
                moons -= 1
                i += 1
    return seeds
