"""Tests for techstats: what a technology or upgrade module does, from the game's technology tables."""

import struct

from nms_connector import techstats
from test_ships import _table

STAT = {name: i for i, name in enumerate(techstats.STAT_NAMES)}


def tech_table() -> bytes:
    """HYPERDRIVE (100 ly + the Ship_Hyperdrive flag) and LASER (base values and an unlocked ability)."""
    def record(tid):
        r = bytearray(0x2E0)
        r[techstats.TECH_ID_AT:techstats.TECH_ID_AT + len(tid)] = tid.encode()
        return bytes(r)
    bonus = lambda name, value: struct.pack("<fiI", value, 1, STAT[name])      # noqa: E731
    return _table([record("HYPERDRIVE"), record("LASER")], 0x2E0,
                  [[bonus("Ship_Hyperdrive", 1.0), bonus("Ship_Hyperdrive_JumpDistance", 100.0)],
                   [bonus("Weapon_Laser_HeatTime", 8.0), bonus("Weapon_Laser_MiningBonus", 1.0),
                    bonus("Weapon_Laser_StrongLaser", 1.0),
                    bonus("Weapon_Laser_Damage", 20.0)]],
                  techstats.TECH_BONUSES_AT)


def proc_table() -> bytes:
    """UP_LASER3 as in build 25625620 (3-4 of four stats) and UP_HYP4 (220-265 ly, always)."""
    def record(pid, nmin, nmax):
        r = bytearray(0x290)
        r[techstats.PROC_ID_AT:techstats.PROC_ID_AT + len(pid)] = pid.encode()
        struct.pack_into("<ii", r, techstats.PROC_COUNTS_AT, nmax, nmin)
        return bytes(r)
    level = lambda name, vmin, vmax, always=0: struct.pack("<IffI?3x", STAT[name], vmax, vmin, 0, always)   # noqa: E731
    return _table([record("UP_LASER3", 3, 4), record("UP_HYP4", 2, 2)], 0x290,
                  [[level("Weapon_Laser_Mining_Speed", 0.8, 0.9), level("Weapon_Laser_HeatTime", 1.2, 1.4),
                    level("Weapon_Laser_ReloadTime", 0.85, 0.9), level("Weapon_Laser_Damage", 30.0, 40.0, 1)],
                   [level("Ship_Hyperdrive_JumpDistance", 220.0, 265.0, 1),
                    level("Ship_Hyperdrive_JumpsPerCell", 1.0, 1.0)]],
                  techstats.PROC_LEVELS_AT)


LABELS = {"WEAPON_LASER_MINING_SPEED": "Mining Speed", "WEAPON_LASER_HEATTIME": "Heat Dispersion",
          "WEAPON_LASER_RELOADTIME": "Overheat Downtime", "WEAPON_LASER_DAMAGE": "Damage",
          "SHIP_HYPERDRIVE_JUMPDISTANCE": "Hyperdrive Range", "WEAPON_LASER_MININGBONUS": "Resources Mined",
          "WEAPON_LASER_STRONGLASER": "Advanced Mining Laser"}


def test_the_stat_enum_matches_the_game():
    """GcStatsTypes indices are the game's: 149 = ship jump distance, 171 = the freighter's (both checked against
    the HYPERDRIVE / F_HYPERDRIVE records on 2026-10-05); localisation keys are cut to 31 characters."""
    assert techstats.JUMP_DISTANCE == 149 and techstats.FREIGHTER_JUMP_DISTANCE == 171
    assert len(techstats.STAT_NAMES) == 209
    assert techstats.text_key(171) == "FREIGHTER_HYPERDRIVE_JUMPDISTAN"
    assert techstats.words(STAT["Ship_Weapons_Missiles_Damage"]) == "Ship weapons missiles damage"


def test_values_read_the_way_the_game_shows_them():
    """Multipliers become percent changes (0.85 = -15 %), improvements named by what they improve read positive
    (Mining Speed 0.9 = +10 %), fractions and percentages become percent, distances light years; a multiplier of
    exactly 1 says nothing."""
    v = techstats.value_text
    assert v(STAT["Weapon_Laser_ReloadTime"], 0.85, 0.9) == "-15 to -10 %"
    assert v(STAT["Weapon_Laser_Mining_Speed"], 0.8, 0.9) == "+10-20 %"
    assert v(STAT["Weapon_Laser_HeatTime"], 1.2, 1.4) == "+20-40 %"
    assert v(STAT["Suit_Armour_Shield_Strength"], 0.2, 0.3) == "+20-30 %"
    assert v(STAT["Weapon_Projectile_Damage"], 3.0, 4.0) == "+3-4 %"
    assert v(STAT["Suit_Armour_Health"], 20.0, 20.0) == "+20"
    assert v(STAT["Ship_Hyperdrive_JumpDistance"], 220.0, 265.0) == "+220-265 ly"
    assert v(STAT["Ship_Maneuverability"], 1.007, 1.007) == "+0.7 %"
    assert v(STAT["Ship_Hyperdrive_JumpsPerCell"], 1.0, 1.0) is None


def test_modifiers_of_upgrades_and_fixed_technology():
    """An upgrade lists every stat it can get with its range ('always' marked) and a note on how many it gets;
    fixed technology shows distances and unlocked abilities but not its base values (LASER heat time 8 is no
    +700 %, its mining bonus 1 no ability). Unknown ids have none; the jump bonuses feed the warp-range estimate."""
    stats = techstats.parse(tech_table(), proc_table())
    label = LABELS.get
    assert stats.modifiers("^UP_LASER3#53433", label) == [
        "Mining Speed +10-20 %", "Heat Dispersion +20-40 %", "Overheat Downtime -15 to -10 %", "Damage +30-40 % (always)"]
    assert stats.note("UP_LASER3#1").startswith("Gets 3-4 of these stats")
    assert stats.modifiers("UP_HYP4#66014", label) == ["Hyperdrive Range +220-265 ly (always)"]
    assert stats.modifiers("HYPERDRIVE", label) == ["Hyperdrive Range +100 ly"]
    assert stats.modifiers("LASER", label) == ["Advanced Mining Laser"]
    assert stats.modifiers("NOPE", label) == [] and stats.note("HYPERDRIVE") is None
    assert stats.jump_bonuses(techstats.JUMP_DISTANCE) == ({"HYPERDRIVE": 100.0}, {"UP_HYP4": (220.0, 265.0)})
    assert "WEAPON_LASER_DAMAGE" in stats.text_keys()


def test_tables_with_another_layout_are_refused():
    """A file that is no table, or whose HYPERDRIVE does not give 100 ly (a moved field after a game update), gives
    None; load() without an installation reports why instead of raising."""
    assert techstats.parse(b"short", b"short") is None
    assert techstats.parse(tech_table().replace(struct.pack("<f", 100.0), struct.pack("<f", 7.0)), proc_table()) is None
    missing = techstats.load(None)
    assert not missing.ready and "not found" in missing.error


def test_upgrade_modules_get_their_description_and_category_keys():
    """Procedural upgrades keep their description key and the name key of the technology they upgrade in 0x80-byte
    fields the item-table calibration never saw (all 199 had no description or category, build 25625620)."""
    def record(pid, desc, group):
        r = bytearray(0x290)
        r[techstats.PROC_ID_AT:techstats.PROC_ID_AT + len(pid)] = pid.encode()
        r[techstats.PROC_DESC_AT:techstats.PROC_DESC_AT + len(desc)] = desc.encode()
        r[techstats.PROC_GROUP_AT:techstats.PROC_GROUP_AT + len(group)] = group.encode()
        return bytes(r)
    table = _table([record("UP_LASER1", "UP_LASER1_DESC", "LASER_NAME_L"), record("UP_X", "", "LASER_NAME_L")], 0x290,
                   [[], []], techstats.PROC_LEVELS_AT)
    assert techstats.procedural_texts(table) == {"UP_LASER1": ("UP_LASER1_DESC", "LASER_NAME_L")}
    assert techstats.procedural_texts(b"short") == {}
