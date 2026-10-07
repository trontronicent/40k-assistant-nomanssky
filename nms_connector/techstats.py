"""What a technology or upgrade module does: its stat modifiers, read from the game's technology tables.

Two tables in ``NMSARC.Precache.pak`` hold them (libMBIN 7.04 layouts, the same as ``ships.py`` reads):

* ``nms_reality_gctechnologytable`` - ``GcTechnology``: id 0x108, ``StatBonuses`` 0x158, a list of
  ``GcStatsBonus {Bonus f32, Level i32, Stat u32}`` (0xC bytes). Fixed technology: HYPERDRIVE gives
  ``Ship_Hyperdrive_JumpDistance`` 100, JET1 a base ``Suit_Jetpack_Tank`` of 2.75 ...
* ``nms_reality_gcproceduraltechnologytable`` - ``GcProceduralTechnologyData``: id 0x40, ``StatLevels`` 0x50, a
  list of ``GcProceduralTechnologyStatLevel {Stat u32, ValueMax f32, ValueMin f32, WeightingCurve u32,
  AlwaysChoose bool}`` (0x14 bytes), ``NumStatsMax``/``NumStatsMin`` at 0x74/0x78. An installed upgrade
  (``^UP_LASER3#53433``) gets between NumStatsMin and NumStatsMax of these stats - the ``AlwaysChoose`` ones
  always - with values inside their range, drawn from the number after ``#``. The game does that drawing itself and
  keeps the result to itself, so the plugin shows the range (the same honest estimate as the warp range).

``Stat`` is the index into ``GcStatsTypes`` (STAT_NAMES, libMBIN 7.04; checked against the game: index 149 is
``Ship_Hyperdrive_JumpDistance`` - HYPERDRIVE must give 100 ly - and 171 the freighter's). The name the game shows
is the localisation key ``<NAME upper-cased, cut to 31 characters>`` (``SHIP_HYPERDRIVE_JUMPDISTANCE`` = "Hyperdrive
Range", ``FREIGHTER_HYPERDRIVE_JUMPDISTAN``); 131 of the 209 stats have one (build 25625620), the others get their
enum name in words.

How a value reads depends on the stat (surveyed over every table entry, build 25625620): multipliers around 1
(``Weapon_Laser_ReloadTime`` 0.85 = -15 %), fractions (``Suit_Armour_Shield_Strength`` 0.2 = +20 %), percentages
(``Weapon_Projectile_Damage`` 3 = +3 %), plain amounts (``Suit_Armour_Health`` 20) and distances (light years).
Some multipliers below 1 are improvements the game names as such (INVERTED: Mining Speed 0.9 reads +10 %).
Values of fixed technology are base values, not bonuses (LASER's ``Weapon_Laser_HeatTime`` 8, a Fusion Engine's
grip 1): of those only the range a drive adds, the abilities a part unlocks (ABILITIES) and a few values the player
knows from the game (BASE_SHOWN: clip size, shots per burst) are shown.

Procedural upgrades also keep their description key and the technology they upgrade in 0x80-byte text fields
(``procedural_texts``), which gamedata uses for their tooltip and category.

Pure apart from ``load`` (blocking file reads).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import mbin
from .hgpak import PakError, PakSet, ZstdUnavailable

TECH_FILE = "metadata/reality/tables/nms_reality_gctechnologytable.mbin"
PROC_FILE = "metadata/reality/tables/nms_reality_gcproceduraltechnologytable.mbin"
TABLE_PAK = "NMSARC.Precache.pak"
TECH_ID_AT, TECH_BONUSES_AT, BONUS_SIZE = 0x108, 0x158, 0xC
PROC_ID_AT, PROC_LEVELS_AT, LEVEL_SIZE, PROC_COUNTS_AT = 0x40, 0x50, 0x14, 0x74
MAX_BONUSES, MAX_LEVELS = 32, 16           # sanity bounds per record (the tables hold at most 8)
KEY_CHARS = 31                             # localisation keys are cut to 31 characters

# GcStatsTypes (libMBIN 7.04, MBINCompiler libMBIN/Source/NMS/GameComponents/GcStatsTypes.cs), in enum order.
STAT_NAMES = (
    "Unspecified", "Weapon_Laser", "Weapon_Laser_Damage", "Weapon_Laser_Mining_Speed", "Weapon_Laser_HeatTime",
    "Weapon_Laser_Bounce", "Weapon_Laser_ReloadTime", "Weapon_Laser_Recoil", "Weapon_Laser_Drain",
    "Weapon_Laser_StrongLaser", "Weapon_Laser_ChargeTime", "Weapon_Laser_MiningBonus", "Weapon_Projectile",
    "Weapon_Projectile_Damage", "Weapon_Projectile_Range", "Weapon_Projectile_Rate", "Weapon_Projectile_ClipSize",
    "Weapon_Projectile_ReloadTime", "Weapon_Projectile_Recoil", "Weapon_Projectile_Bounce", "Weapon_Projectile_Homing",
    "Weapon_Projectile_Dispersion", "Weapon_Projectile_BulletsPerShot", "Weapon_Projectile_MinimumCharge",
    "Weapon_Projectile_MaximumCharge", "Weapon_Projectile_BurstCap", "Weapon_Projectile_BurstCooldown",
    "Weapon_ChargedProjectile", "Weapon_ChargedProjectile_ChargeTime", "Weapon_ChargedProjectile_CooldownDuration",
    "Weapon_ChargedProjectile_Drain", "Weapon_ChargedProjectile_ExtraSpeed", "Weapon_Rail", "Weapon_Shotgun",
    "Weapon_Burst", "Weapon_Flame", "Weapon_Cannon", "Weapon_Grenade", "Weapon_Grenade_Damage", "Weapon_Grenade_Radius",
    "Weapon_Grenade_Speed", "Weapon_Grenade_Bounce", "Weapon_Grenade_Homing", "Weapon_Grenade_Clusterbomb",
    "Weapon_TerrainEdit", "Weapon_Gravity", "Weapon_SunLaser", "Weapon_SoulLaser", "Weapon_MineGrenade",
    "Weapon_FrontShield", "Weapon_Scope", "Weapon_Spawner", "Weapon_SpawnerAlt", "Weapon_Melee", "Weapon_StunGrenade",
    "Weapon_Stealth", "Weapon_Scan", "Weapon_Scan_Radius", "Weapon_Scan_Recharge_Time", "Weapon_Scan_Types",
    "Weapon_Scan_Binoculars", "Weapon_Scan_Discovery_Creature", "Weapon_Scan_Discovery_Flora",
    "Weapon_Scan_Discovery_Mineral", "Weapon_Scan_Secondary", "Weapon_Scan_Terrain_Resource", "Weapon_Scan_Surveying",
    "Weapon_Scan_BuilderReveal", "Weapon_Fish", "Weapon_Stun", "Weapon_Stun_Duration", "Weapon_Stun_Damage_Multiplier",
    "Weapon_FireDOT", "Weapon_FireDOT_Duration", "Weapon_FireDOT_DPS", "Weapon_FireDOT_Damage_Multiplier",
    "Suit_Armour_Health", "Suit_Armour_Shield", "Suit_Armour_Shield_Strength", "Suit_Energy", "Suit_Energy_Regen",
    "Suit_Protection", "Suit_Protection_Cold", "Suit_Protection_Heat", "Suit_Protection_Toxic",
    "Suit_Protection_Radiation", "Suit_Protection_Spook", "Suit_Protection_Pressure", "Suit_Underwater",
    "Suit_UnderwaterLifeSupport", "Suit_DamageReduce_Cold", "Suit_DamageReduce_Heat", "Suit_DamageReduce_Toxic",
    "Suit_DamageReduce_Radiation", "Suit_Protection_HeatDrain", "Suit_Protection_ColdDrain", "Suit_Protection_ToxDrain",
    "Suit_Protection_RadDrain", "Suit_Protection_WaterDrain", "Suit_Protection_SpookDrain", "Suit_Stamina_Strength",
    "Suit_Stamina_Speed", "Suit_Stamina_Recovery", "Suit_Jetpack", "Suit_Jetpack_Tank", "Suit_Jetpack_Drain",
    "Suit_Jetpack_Refill", "Suit_Jetpack_Ignition", "Suit_Jetpack_DoubleJump", "Suit_Jetpack_WaterEfficiency",
    "Suit_Jetpack_MidairRefill", "Suit_Refiner", "Suit_AutoTranslator", "Suit_Utility", "Suit_RocketLocker",
    "Suit_FishPlatform", "Suit_FoodUnit", "Suit_Denier", "Suit_Vehicle_Summon", "Ship_Weapons_Guns",
    "Ship_Weapons_Guns_Damage", "Ship_Weapons_Guns_Rate", "Ship_Weapons_Guns_HeatTime", "Ship_Weapons_Guns_CoolTime",
    "Ship_Weapons_Guns_Scale", "Ship_Weapons_Guns_BulletsPerShot", "Ship_Weapons_Guns_Dispersion",
    "Ship_Weapons_Guns_Range", "Ship_Weapons_Guns_Damage_Radius", "Ship_Weapons_Lasers", "Ship_Weapons_Lasers_Damage",
    "Ship_Weapons_Lasers_HeatTime", "Ship_Weapons_Missiles", "Ship_Weapons_Missiles_NumPerShot",
    "Ship_Weapons_Missiles_Speed", "Ship_Weapons_Missiles_Damage", "Ship_Weapons_Missiles_Size",
    "Ship_Weapons_Shotgun", "Ship_Weapons_MiniGun", "Ship_Weapons_Plasma", "Ship_Weapons_Rockets",
    "Ship_Weapons_ShieldLeech", "Ship_Armour_Shield", "Ship_Armour_Shield_Strength", "Ship_Armour_Health", "Ship_Scan",
    "Ship_Scan_EconomyFilter", "Ship_Scan_ConflictFilter", "Ship_Hyperdrive", "Ship_Hyperdrive_JumpDistance",
    "Ship_Hyperdrive_JumpsPerCell", "Ship_Hyperdrive_QuickWarp", "Ship_Launcher", "Ship_Launcher_TakeOffCost",
    "Ship_Launcher_AutoCharge", "Ship_PulseDrive", "Ship_PulseDrive_MiniJumpFuelSpending",
    "Ship_PulseDrive_MiniJumpSpeed", "Ship_Boost", "Ship_Maneuverability", "Ship_BoostManeuverability",
    "Ship_LifeSupport", "Ship_Drift", "Ship_Inventory", "Ship_Tech_Slots", "Ship_Cargo_Slots", "Ship_Teleport",
    "Ship_CargoShield", "Ship_WaterLandingJet", "Ship_TractorBeam", "Freighter_Hyperdrive",
    "Freighter_Hyperdrive_JumpDistance", "Freighter_Hyperdrive_JumpsPerCell", "Freighter_MegaWarp",
    "Freighter_Teleport", "Freighter_Fleet_Boost", "Freighter_Fleet_Speed", "Freighter_Fleet_Fuel",
    "Freighter_Fleet_Combat", "Freighter_Fleet_Trade", "Freighter_Fleet_Explore", "Freighter_Fleet_Mine",
    "Vehicle_Boost", "Vehicle_Engine", "Vehicle_Scan", "Vehicle_EngineFuelUse", "Vehicle_EngineTopSpeed",
    "Vehicle_BoostSpeed", "Vehicle_BoostTanks", "Vehicle_Grip", "Vehicle_SkidGrip", "Vehicle_SubBoostSpeed",
    "Vehicle_Laser", "Vehicle_LaserDamage", "Vehicle_LaserHeatTime", "Vehicle_LaserStrongLaser", "Vehicle_Gun",
    "Vehicle_GunDamage", "Vehicle_GunHeatTime", "Vehicle_GunRate", "Vehicle_StunGun", "Vehicle_TerrainEdit",
    "Vehicle_FuelRegen", "Vehicle_AutoPilot", "Vehicle_Flame", "Vehicle_FlameDamage", "Vehicle_FlameHeatTime",
    "Vehicle_Refiner", "Vehicle_Plough",
)
JUMP_DISTANCE = STAT_NAMES.index("Ship_Hyperdrive_JumpDistance")                  # 149
FREIGHTER_JUMP_DISTANCE = STAT_NAMES.index("Freighter_Hyperdrive_JumpDistance")   # 171

# How a stat's value reads (see the module docstring). Everything else is a multiplier around 1.
DISTANCE = {"Ship_Hyperdrive_JumpDistance", "Freighter_Hyperdrive_JumpDistance"}
FRACTION = {"Suit_Armour_Shield_Strength", "Ship_Armour_Shield_Strength", "Suit_Energy", "Suit_Stamina_Strength",
            "Suit_Jetpack_Tank", "Ship_Weapons_ShieldLeech", "Vehicle_BoostSpeed", "Vehicle_BoostTanks",
            "Vehicle_SubBoostSpeed"}
PERCENT = {"Weapon_Laser_Damage", "Weapon_Projectile_Damage", "Ship_Weapons_Guns_Damage", "Ship_Weapons_Lasers_Damage",
           "Vehicle_LaserDamage", "Vehicle_GunDamage", "Weapon_Scan_Discovery_Creature", "Weapon_Scan_Discovery_Flora",
           "Weapon_Scan_Discovery_Mineral", "Weapon_ChargedProjectile_ExtraSpeed"}
AMOUNT = {"Suit_Armour_Health", "Weapon_Projectile_ClipSize", "Weapon_Projectile_BurstCap",
          "Weapon_Projectile_MaximumCharge", "Suit_Protection_Cold", "Suit_Protection_Heat", "Suit_Protection_Toxic",
          "Suit_Protection_Radiation", "Suit_Underwater", "Ship_Cargo_Slots", "Ship_Tech_Slots",
          "Weapon_Grenade_Damage", "Weapon_Grenade_Bounce", "Weapon_Grenade_Speed"}
# Multipliers below 1 that are improvements, under a name the game gives the improvement: Mining Speed 0.9 (the
# laser needs 90 % of the time) reads +10 %, Fuel Efficiency 0.85 (Suit_Jetpack_Drain) +15 %. Stats named for what
# they cost (Launch Cost, Overheat Downtime, Reload Time) keep their sign.
INVERTED = {"Weapon_Laser_Mining_Speed", "Suit_Jetpack_Drain", "Suit_DamageReduce_Cold", "Suit_DamageReduce_Heat",
            "Suit_DamageReduce_Toxic", "Suit_DamageReduce_Radiation", "Ship_PulseDrive_MiniJumpFuelSpending",
            "Freighter_Fleet_Fuel", "Vehicle_LaserHeatTime", "Vehicle_GunHeatTime", "Vehicle_GunRate",
            "Weapon_ChargedProjectile_ChargeTime", "Ship_Weapons_Guns_CoolTime"}


# Stats of fixed technology that are abilities it unlocks (the game names them so: "Advanced Mining Laser",
# "Surveying Enabled"), and base values worth showing as they are ("Clip Size 64"). Chosen from every fixed
# technology's stats, build 25625620; the rest are base values that only mean something inside the game's formulas.
ABILITIES = {"Weapon_Laser_StrongLaser", "Weapon_Scan_Surveying", "Weapon_Scan_BuilderReveal", "Weapon_Stealth",
             "Weapon_Fish", "Weapon_Stun", "Weapon_FireDOT", "Weapon_SunLaser", "Weapon_SoulLaser",
             "Suit_Jetpack_DoubleJump", "Suit_Jetpack_WaterEfficiency", "Suit_Jetpack_MidairRefill",
             "Suit_UnderwaterLifeSupport", "Suit_Protection_Pressure", "Suit_RocketLocker", "Ship_LifeSupport",
             "Ship_Hyperdrive_QuickWarp", "Ship_Launcher_AutoCharge", "Ship_TractorBeam", "Ship_Weapons_ShieldLeech",
             "Vehicle_AutoPilot", "Vehicle_LaserStrongLaser", "Vehicle_Plough", "Freighter_Fleet_Boost"}
BASE_SHOWN = {"Weapon_Projectile_ClipSize", "Weapon_Projectile_BurstCap", "Ship_Teleport", "Freighter_Teleport"}


def stat_name(stat: int) -> str:
    return STAT_NAMES[stat] if 0 <= stat < len(STAT_NAMES) else f"Stat {stat}"


def text_key(stat: int) -> str:
    """The localisation key of a stat's name: 149 -> 'SHIP_HYPERDRIVE_JUMPDISTANCE'."""
    return stat_name(stat).upper()[:KEY_CHARS]


def words(stat: int) -> str:
    """A stat without a game text, in words: 'Ship_Weapons_Missiles_Damage' -> 'Ship weapons missiles damage'."""
    return stat_name(stat).replace("_", " ").capitalize()


def kind(stat: int) -> str:
    """'distance', 'fraction', 'percent', 'amount', 'inverted' (a multiplier where less is better) or 'multiplier'."""
    name = stat_name(stat)
    for label, names in (("distance", DISTANCE), ("fraction", FRACTION), ("percent", PERCENT), ("amount", AMOUNT),
                         ("inverted", INVERTED)):
        if name in names:
            return label
    return "multiplier"


def _num(value: float) -> str:
    """12.0 -> '12', 2.5 -> '2.5', 1234.0 -> '1,234'."""
    return f"{value:,.0f}" if abs(value - round(value)) < 0.05 else f"{value:,.1f}"


def _signed(value: float) -> str:
    return ("+" if value >= 0 else "-") + _num(abs(value))


def value_text(stat: int, low: float, high: float) -> str | None:
    """A stat's value or range as the player reads it ('+220-265 ly', '-15 to -10 %', '+20 %'); None when it
    changes nothing (a multiplier of exactly 1)."""
    k = kind(stat)
    if k == "multiplier":
        low, high = (low - 1) * 100, (high - 1) * 100
    elif k == "inverted":
        low, high = (1 - low) * 100, (1 - high) * 100
    elif k == "fraction":
        low, high = low * 100, high * 100
    low, high = min(low, high), max(low, high)
    if k in ("multiplier", "inverted") and abs(low) < 0.05 and abs(high) < 0.05:
        return None
    unit = {"distance": " ly", "amount": ""}.get(k, " %")
    if abs(high - low) < 0.05:
        return _signed(low) + unit
    if low < 0 < high or high < 0:
        return f"{_signed(low)} to {_signed(high)}{unit}"
    return f"{_signed(low)}-{_num(high)}{unit}"


@dataclass(frozen=True)
class StatRange:
    """One stat of a technology: a fixed value (low == high) or a procedural upgrade's range."""
    stat: int
    low: float
    high: float
    always: bool = False        # a procedural upgrade always gets this stat (AlwaysChoose)


@dataclass(frozen=True)
class ProceduralRule:
    """The stats a procedural upgrade can get and how many of them it gets."""
    stats: tuple[StatRange, ...]
    count: tuple[int, int]      # (NumStatsMin, NumStatsMax)


def _list(data: bytes, pos: int) -> tuple[int, int]:
    """(absolute start, count) of the list whose 16-byte header is at `pos`."""
    offset, count = struct.unpack_from("<QI", data, pos)
    return pos + offset, count


@dataclass
class TechStats:
    """The stat modifiers of every technology and procedural upgrade of one game build."""
    fixed: dict[str, tuple[StatRange, ...]] = field(default_factory=dict)
    procedural: dict[str, ProceduralRule] = field(default_factory=dict)
    source: str = "none"
    error: str | None = None

    @property
    def ready(self) -> bool:
        return bool(self.fixed or self.procedural)

    @staticmethod
    def key(item_id: str) -> str:
        """'^UP_HYP4#66014' -> 'UP_HYP4'."""
        return str(item_id or "").lstrip("^").split("#", 1)[0]

    def jump_bonuses(self, stat: int) -> tuple[dict[str, float], dict[str, tuple[float, float]]]:
        """({tech id: value}, {upgrade id: (min, max)}) of one stat - the warp-range tables (ships.py)."""
        fixed = {tid: s.low for tid, stats in self.fixed.items() for s in stats if s.stat == stat and s.low > 0}
        procedural = {pid: (s.low, s.high) for pid, rule in self.procedural.items() for s in rule.stats
                      if s.stat == stat and 0 < s.low <= s.high}
        return fixed, procedural

    def text_keys(self) -> set[str]:
        """The localisation keys of every stat these tables use (resolved once per build by GameData)."""
        stats = {s.stat for v in self.fixed.values() for s in v}
        stats |= {s.stat for rule in self.procedural.values() for s in rule.stats}
        return {text_key(s) for s in stats}

    def modifiers(self, item_id: str, label) -> list[str]:
        """What a technology does, one line per stat ('Hyperdrive Range +220-265 ly (always)').

        ``label(text_key)`` -> the stat's name in the player's languages, or None (then the enum name in words).
        Procedural upgrades list every stat they can get. Fixed technology lists the range it adds, the abilities
        it unlocks (ABILITIES) and a few base values the player knows from the game (BASE_SHOWN, unsigned); its
        other values are base values that read wrongly as bonuses (LASER's heat time 8, a Fusion Engine's grip 1).
        """
        key = self.key(item_id)

        def name(stat):
            return label(text_key(stat)) or words(stat)
        lines = []
        rule = self.procedural.get(key)
        if rule:
            for s in rule.stats:
                value = value_text(s.stat, s.low, s.high)
                if value:
                    lines.append(f"{name(s.stat)} {value}" + (" (always)" if s.always else ""))
            return lines
        for s in self.fixed.get(key, ()):
            stat = stat_name(s.stat)
            if stat in DISTANCE and s.low > 0:
                lines.append(f"{name(s.stat)} {value_text(s.stat, s.low, s.high)}")
            elif stat in BASE_SHOWN and s.low > 0:
                lines.append(f"{name(s.stat)} {_num(s.low)}")
            elif stat in ABILITIES and s.low > 0:
                lines.append(name(s.stat))
        return lines

    def note(self, item_id: str) -> str | None:
        """How a procedural upgrade's values are decided ('Gets 2-4 of these stats ...'), None for fixed tech."""
        rule = self.procedural.get(self.key(item_id))
        if not rule:
            return None
        lo, hi = rule.count
        count = f"{lo}" if lo == hi else f"{lo}-{hi}"
        return (f"Gets {count} of these stats, with values inside these ranges; the game draws them from the "
                "upgrade's seed and does not store the result, so only the ranges are known.")


PROC_DESC_AT, PROC_GROUP_AT, PROC_TEXT_SIZE = 0x84, 0x184, 0x80   # NMSString0x80: Description, NameLower


def procedural_texts(proc: bytes) -> dict[str, tuple[str, str]]:
    """{upgrade id: (description key, name key of the technology it upgrades)} - 'UP_LASER1' -> ('UP_LASER1_DESC',
    'LASER_NAME_L'). The item-table calibration (mbin) finds only 0x20-byte keys, so procedural upgrades had no
    description or category (all 199, build 25625620); these 0x80-byte fields hold them. {} when unreadable."""
    out: dict[str, tuple[str, str]] = {}
    try:
        start, count = mbin.root_list(proc)
        size = mbin.record_size(proc, start, count)
        for k in range(count):
            p = start + k * size
            pid = mbin.fixed_str(proc, p + PROC_ID_AT, 0x10)
            desc = mbin.fixed_str(proc, p + PROC_DESC_AT, PROC_TEXT_SIZE)
            group = mbin.fixed_str(proc, p + PROC_GROUP_AT, PROC_TEXT_SIZE)
            if pid and desc and group and mbin.KEY_RE.match(desc) and mbin.KEY_RE.match(group):
                out[pid] = (desc, group)
    except (struct.error, mbin.MbinError, IndexError):
        return {}
    return out


def parse(tech: bytes, proc: bytes) -> TechStats | None:
    """The stat modifiers of both tables; None when the layout is not the expected one (HYPERDRIVE must give
    Ship_Hyperdrive_JumpDistance 100 and some upgrade must have stat levels)."""
    stats = TechStats(source="game files")
    try:
        start, count = mbin.root_list(tech)
        size = mbin.record_size(tech, start, count)
        for k in range(count):
            p = start + k * size
            tid = mbin.fixed_str(tech, p + TECH_ID_AT, 0x10)
            if not tid:
                continue
            at, n = _list(tech, p + TECH_BONUSES_AT)
            bonuses = []
            for j in range(min(n, MAX_BONUSES)):
                bonus, _level, stat = struct.unpack_from("<fiI", tech, at + j * BONUS_SIZE)
                bonuses.append(StatRange(stat, round(bonus, 3), round(bonus, 3)))
            stats.fixed[tid] = tuple(bonuses)
        start, count = mbin.root_list(proc)
        size = mbin.record_size(proc, start, count)
        for k in range(count):
            p = start + k * size
            pid = mbin.fixed_str(proc, p + PROC_ID_AT, 0x10)
            if not pid:
                continue
            at, n = _list(proc, p + PROC_LEVELS_AT)
            levels = []
            for j in range(min(n, MAX_LEVELS)):
                q = at + j * LEVEL_SIZE
                stat, vmax, vmin = struct.unpack_from("<Iff", proc, q)
                levels.append(StatRange(stat, round(min(vmin, vmax), 3), round(max(vmin, vmax), 3), proc[q + 0x10] == 1))
            nmax, nmin = struct.unpack_from("<ii", proc, p + PROC_COUNTS_AT)
            if not 0 <= nmin <= nmax <= MAX_LEVELS:
                nmin, nmax = 0, len(levels)
            stats.procedural[pid] = ProceduralRule(tuple(levels), (nmin, nmax))
    except (struct.error, mbin.MbinError, IndexError):
        return None
    hyperdrive = {s.stat: s.low for s in stats.fixed.get("HYPERDRIVE", ())}
    if hyperdrive.get(JUMP_DISTANCE) != 100.0 or not any(r.stats for r in stats.procedural.values()):
        return None
    return stats


def load(install) -> TechStats:
    """The installed game's tables; an empty TechStats with ``error`` set when they cannot be read."""
    if install is None:
        return TechStats(error="game installation not found")
    try:
        with PakSet(install.pcbanks, {TECH_FILE: TABLE_PAK, PROC_FILE: TABLE_PAK}) as paks:
            stats = parse(paks.read(TECH_FILE), paks.read(PROC_FILE))
    except (KeyError, OSError, PakError, ZstdUnavailable) as exc:
        return TechStats(error=f"{type(exc).__name__}: {exc}")
    return stats or TechStats(error="the game's technology tables changed layout (a game update?)")
