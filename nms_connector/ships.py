"""Your starships from the save: type, class, base stats, technology and an estimate of the warp range.

The save keeps per ship (``ShipOwnership``) its model (``Resource.Filename`` -> type), ``Inventory`` with
``Class`` (C/B/A/S), ``BaseStatValues`` (the ship's own bonuses in percent: ``^SHIP_DAMAGE``, ``^SHIP_SHIELD``,
``^SHIP_HYPERDRIVE``, ``^SHIP_AGILE``) and the installed technology (slots of type Technology in ``Inventory``
and ``Inventory_TechOnly``; ``Amount`` = charge, -1 for technology that needs none).

**Warp range** is not stored: the game adds up the ``Ship_Hyperdrive_JumpDistance`` bonuses of the installed
technology (``nms_reality_gctechnologytable``: HYPERDRIVE 100 ly, the Sentinel/exotic drives 600 ly) and of the
procedural upgrades (``nms_reality_gcproceduraltechnologytable``: UP_HYP4 220-265 ly - the exact value is drawn
from the upgrade's seed, ``^UP_HYP4#66014``, so only its range is known). The ship's own hyperdrive bonus is
applied on top. Adjacency and supercharged slots can add more, so the result is shown as an estimate (a lower
and an upper bound). Read 2026-10-04 from build 25625620: HDRIVEBOOST1-4 add no range - they open red, green,
blue and purple star systems.

Offsets: libMBIN 7.04 GcTechnology (ID 0x108, StatBonuses 0x158; GcStatsBonus {Bonus f32, Level i32, Stat u32},
0xC bytes) and GcProceduralTechnologyData (ID 0x40, StatLevels 0x50; {Stat u32, ValueMax f32, ValueMin f32, ...},
0x14 bytes); GcStatsTypes Ship_Hyperdrive_JumpDistance = 149. Checked by the table itself: HYPERDRIVE must give
100 ly, otherwise the measured FALLBACK is used.
"""

from __future__ import annotations

from . import equipment, techstats
from .summary import ship_class

# The tables and their layout are read by techstats.py (every stat of every technology); this module uses the
# jump-distance stats. Re-exported for the tests that build fake tables.
TECH_FILE, PROC_FILE, TABLE_PAK = techstats.TECH_FILE, techstats.PROC_FILE, techstats.TABLE_PAK
JUMP_DISTANCE = techstats.JUMP_DISTANCE                      # 149: GcStatsTypes.Ship_Hyperdrive_JumpDistance
FREIGHTER_JUMP_DISTANCE = techstats.FREIGHTER_JUMP_DISTANCE  # 171: F_HYPERDRIVE 100 ly, UP_FRHYP*
TECH_ID_AT, TECH_BONUSES_AT, BONUS_SIZE = techstats.TECH_ID_AT, techstats.TECH_BONUSES_AT, techstats.BONUS_SIZE
PROC_ID_AT, PROC_LEVELS_AT, LEVEL_SIZE = techstats.PROC_ID_AT, techstats.PROC_LEVELS_AT, techstats.LEVEL_SIZE

STAR_COLOURS = {"HDRIVEBOOST1": "red", "HDRIVEBOOST2": "green", "HDRIVEBOOST3": "blue", "HDRIVEBOOST4": "purple"}
BASE_STATS = {"^SHIP_DAMAGE": "damage", "^SHIP_SHIELD": "shield", "^SHIP_HYPERDRIVE": "hyperdrive", "^SHIP_AGILE": "agility"}

# Measured from the game's files on 2026-10-04 (build 25625620): used when they cannot be read.
FALLBACK = {
    "fixed": {"HYPERDRIVE": 100.0, "WARP_ALIEN": 100.0, "HYPERDRIVE_SPEC": 600.0, "HYPERDRIVE_ROBO": 600.0},
    "procedural": {"UP_HYP0": (10.0, 25.0), "UP_HYP1": (50.0, 100.0), "UP_HYP2": (115.0, 165.0),
                   "UP_HYP3": (165.0, 220.0), "UP_HYP4": (220.0, 265.0), "UP_HYPX": (50.0, 320.0),
                   "CV_HYP2": (115.0, 165.0), "CV_HYP3": (165.0, 220.0), "UA_HYP1": (50.0, 100.0),
                   "UA_HYP2": (115.0, 165.0), "UA_HYP3": (165.0, 220.0), "UA_HYP4": (220.0, 265.0)},
    "freighter_fixed": {"F_HYPERDRIVE": 100.0},
    "freighter_procedural": {"UP_FRHYP1": (50.0, 100.0), "UP_FRHYP2": (100.0, 150.0), "UP_FRHYP3": (150.0, 200.0),
                             "UP_FRHYP4": (200.0, 250.0)},
    "source": "built-in (measured 2026-10-04)",
}


def tables_from(stats: techstats.TechStats) -> dict | None:
    """{fixed: {tech id: ly}, procedural: {id: (min, max)}, freighter_*} - the jump-distance bonuses of the parsed
    technology tables; None when HYPERDRIVE does not give 100 ly or no upgrade adds range (a moved layout)."""
    fixed, procedural = stats.jump_bonuses(JUMP_DISTANCE)
    freighter_fixed, freighter_procedural = stats.jump_bonuses(FREIGHTER_JUMP_DISTANCE)
    if fixed.get("HYPERDRIVE") != 100.0 or not procedural:
        return None
    return {"fixed": fixed, "procedural": procedural, "freighter_fixed": freighter_fixed or FALLBACK["freighter_fixed"],
            "freighter_procedural": freighter_procedural or FALLBACK["freighter_procedural"], "source": "game files"}


def parse_tables(tech: bytes, proc: bytes) -> dict | None:
    """tables_from() of the raw table files (see techstats.parse); None when they cannot be read."""
    stats = techstats.parse(tech, proc)
    return tables_from(stats) if stats else None


def load_tables(install, stats: techstats.TechStats | None = None) -> dict:
    """The warp-range tables of the installed game (from ``stats`` when already loaded), else FALLBACK
    (``source`` says which, ``error`` why)."""
    stats = stats if stats is not None else techstats.load(install)
    if stats.error:
        return dict(FALLBACK, error=stats.error)
    return tables_from(stats) or dict(FALLBACK, error="the game's technology tables changed layout (a game update?)")


def tech_id(raw: str | None) -> str:
    """'^UP_HYP4#66014' -> 'UP_HYP4' (the table id; the number seeds a procedural upgrade's values)."""
    return str(raw or "").lstrip("^").split("#", 1)[0]


def _technology(ship: dict) -> list[dict]:
    """The technology slots of a ship (or anything with ``Inventory_TechOnly`` and ``Inventory``)."""
    return equipment.technology_in(ship.get("Inventory_TechOnly"), ship.get("Inventory"))


DAMAGED_PREFIX = equipment.DAMAGED_PREFIX   # a damaged slot shows as this technology until it is repaired


def damaged_slots(ship: dict) -> int:
    return sum(1 for t in ship["technology"] if t["id"].startswith(DAMAGED_PREFIX))


def _slots(inventory: dict | None) -> int:
    return len((inventory or {}).get("ValidSlotIndices") or [])


def ships_from_save(readable: dict) -> list[dict]:
    """Your ships (unused slots of ShipOwnership left out), the primary one first."""
    ps = ((readable or {}).get("BaseContext") or {}).get("PlayerStateData") or {}
    out = []
    for i, ship in enumerate(ps.get("ShipOwnership") or []):
        filename = ((ship or {}).get("Resource") or {}).get("Filename") or ""
        if not filename:
            continue
        inv = ship.get("Inventory") or {}
        stats = {BASE_STATS[s["BaseStatID"]]: round(float(s.get("Value") or 0), 1)
                 for s in inv.get("BaseStatValues") or [] if s.get("BaseStatID") in BASE_STATS}
        out.append({"index": i, "name": ship.get("Name") or "", "type": ship_class(filename),
                    "class": ((inv.get("Class") or {}).get("InventoryClass")) or "?", "primary": i == ps.get("PrimaryShip"),
                    "stats": stats, "technology": _technology(ship),
                    "slots": _slots(inv), "cargo_slots": _slots(ship.get("Inventory_Cargo")),
                    "tech_slots": _slots(ship.get("Inventory_TechOnly"))})
    out.sort(key=lambda s: (not s["primary"], s["index"]))
    return out


def warp_range(ship: dict, tables: dict) -> dict:
    """{low, high, parts: [(tech id, low, high)], bonus, colours}: the warp range in light years estimated from
    the installed technology and the ship's own hyperdrive bonus; low = high = 0 without a hyperdrive."""
    parts = []
    for tech in ship["technology"]:
        tid = tech_id(tech["id"])
        if tid in tables["fixed"]:
            parts.append((tid, tables["fixed"][tid], tables["fixed"][tid]))
        elif tid in tables["procedural"]:
            parts.append((tid, *tables["procedural"][tid]))
    bonus = ship["stats"].get("hyperdrive", 0.0)
    factor = 1 + bonus / 100
    low = sum(p[1] for p in parts) * factor if any(p[0] in tables["fixed"] for p in parts) else 0.0
    high = sum(p[2] for p in parts) * factor if low else 0.0
    colours = [STAR_COLOURS[t] for t in STAR_COLOURS if any(tech_id(x["id"]) == t for x in ship["technology"])]
    return {"low": round(low), "high": round(high), "parts": parts, "bonus": bonus, "colours": colours}


def freighter_from_save(readable: dict) -> dict | None:
    """Your freighter's name, class and technology (FreighterInventory_TechOnly + FreighterInventory), or None."""
    ps = ((readable or {}).get("BaseContext") or {}).get("PlayerStateData") or {}
    tech_inv = ps.get("FreighterInventory_TechOnly") or {}
    if not tech_inv and not ps.get("FreighterInventory"):
        return None
    ship = {"Inventory_TechOnly": tech_inv, "Inventory": ps.get("FreighterInventory") or {}}
    return {"name": ps.get("PlayerFreighterName") or "", "class": ((tech_inv.get("Class") or {}).get("InventoryClass")) or "?",
            "technology": _technology(ship)}


def freighter_range(freighter: dict, tables: dict) -> dict:
    """Like warp_range, for the freighter's hyperdrive (Freighter_Hyperdrive_JumpDistance)."""
    as_ship = {"technology": freighter["technology"], "stats": {}}
    fr = {"fixed": tables.get("freighter_fixed") or FALLBACK["freighter_fixed"],
          "procedural": tables.get("freighter_procedural") or FALLBACK["freighter_procedural"]}
    return warp_range(as_ship, fr)


def range_text(estimate: dict) -> str:
    if not estimate["low"]:
        return "no hyperdrive"
    if estimate["low"] == estimate["high"]:
        return f"~{estimate['low']:,} ly"
    return f"~{estimate['low']:,}-{estimate['high']:,} ly"


def ship_label(ship: dict) -> str:
    return ship["name"] or f"(unnamed {ship['type']})"


def primary_range(items: list[dict], tables: dict) -> dict | None:
    """The primary ship's warp-range estimate with its name, or None."""
    primary = next((s for s in items if s["primary"]), None)
    if primary is None:
        return None
    return dict(warp_range(primary, tables), ship=ship_label(primary))


def _pct(value: float | None) -> str | None:
    return None if value is None else f"+{value:.1f} %"


def ship_sections(items: list[dict], tables: dict, texts) -> list[dict]:
    """The ships table (type, class, warp range, star colours, base stats, slots) and every ship's technology
    with what it does (one sub-tab per ship, the primary one first)."""
    if not items:
        return [{"type": "text", "text": "No ships in this save."}]
    rows = []
    for s in items:
        est = warp_range(s, tables)
        parts = "\n".join(f"{texts.name(p[0]) or p[0]}: " + (f"{p[1]:.0f} ly" if p[1] == p[2] else f"{p[1]:.0f}-{p[2]:.0f} ly")
                          for p in est["parts"])
        hint = (f"{parts}\nShip's own hyperdrive bonus: +{est['bonus']:.1f} %\nAdjacent and supercharged slots can add "
                "more; procedural upgrades get their exact value from a seed the game keeps to itself.") if est["parts"] else None
        rows.append([ship_label(s) + (" (primary)" if s["primary"] else ""), s["type"], s["class"],
                     {"text": range_text(est), "hint": hint} if hint else range_text(est),
                     ", ".join(est["colours"]) or "yellow only",
                     _pct(s["stats"].get("damage")), _pct(s["stats"].get("shield")), _pct(s["stats"].get("hyperdrive")),
                     _pct(s["stats"].get("agility")),
                     f"{s['slots']} / {s['cargo_slots']} / {s['tech_slots']}"
                     + (f" ({damaged_slots(s)} damaged)" if damaged_slots(s) else "")])
    out = [{"type": "table", "id": "ships", "title": f"Ships ({len(items)})",
            "columns": ["Ship", "Type", "Class", "Warp range (estimate)", "Star colours it can reach", "Damage",
                        "Shield", "Hyperdrive", "Maneuverability", "Slots (general / cargo / tech)"],
            "rows": rows}]
    def adds(raw_id: str) -> str | None:
        """What the stat list does not say: the star colours a drive opens; the warp range when the technology
        tables' stats are not available (texts without modifiers)."""
        tid = tech_id(raw_id)
        if tid in STAR_COLOURS:
            return f"opens {STAR_COLOURS[tid]} star systems"
        if hasattr(texts, "modifiers") and texts.modifiers(raw_id):
            return None
        if tid in tables["fixed"]:
            return f"{tables['fixed'][tid]:.0f} ly warp range"
        if tid in tables["procedural"]:
            low, high = tables["procedural"][tid]
            return f"{low:.0f}-{high:.0f} ly warp range"
        return None

    # One sub-tab per ship, the primary one first (its table keeps the id the page focused before 0.10.0).
    out.append({"type": "tabs", "id": "ship-tech", "tabs": [
        {"id": f"ship-{s['index']}", "label": ship_label(s) + (" (primary)" if s["primary"] else ""),
         "sections": [equipment.technology_table(s["technology"], texts, f"Technology of {ship_label(s)}",
                                                 "primary-ship-tech" if s["primary"] else None, adds)]}
        for s in items]})
    note = ("Warp range is an estimate from the installed hyperdrive technology (values from the game's "
            "technology tables): the game draws each procedural upgrade's exact value from its seed, and adjacent "
            "or supercharged slots add more. The route planner starts with the lower value.")
    if tables.get("error"):
        note += f" Technology values: built-in ({tables['error']})."
    out.append({"type": "text", "text": note})
    return out
