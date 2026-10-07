"""Your freighter's frigates from the save: class, grade, race, stats, traits, expedition record.

``FleetFrigates`` holds per frigate ``FrigateClass``, ``Race``, ``InventoryClass`` (grade C-S), ``Stats`` (int[11] by
GcFrigateStatType: Combat, Exploration, Mining, Diplomatic, FuelBurnRate, FuelCapacity, Speed, ExtraLoot, Repair,
Invulnerable, Stealth), ``TraitIDs`` (``^FUEL_PRI``; "^" = empty slot), ``TotalNumberOfExpeditions`` /
``...SuccessfulEvents`` / ``...FailedEvents``, ``DamageTaken`` and ``HomeSystemSeed`` (the packed address of the
system it was bought in; old frigates hold a random seed there). A frigate is out when an entry of
``FleetExpeditions`` lists its index in ``AllFrigateIndices``.

Trait names come from ``metadata/reality/tables/frigatetraittable.mbin`` (GcFrigateTraitData, libMBIN 7.04: record
0x68 - DisplayName 0x20A key at 0x00, ID at 0x20, FrigateStatType u32 at 0x5C, Strength u32 at 0x60; 178 traits in
build 25625620, e.g. FUEL_PRI = FLEET_TRAIT_PRI_FUEL_1). Icons: the fleet screen's
``textures/ui/frontend/icons/fleet/frigate/frigate.<class>.dds`` and ``.../property/property.<primary|negative>.<stat>``
(gamedata.EXTRA_ICONS: FRIGATE_CLASS_<CLASS>, FRIGATE_TRAIT_<PRIMARY|NEGATIVE>_<STAT>).
"""

from __future__ import annotations

import struct

from . import mbin

TRAIT_FILE = "metadata/reality/tables/frigatetraittable.mbin"
TRAIT_PAK = "NMSARC.Precache.pak"      # metadata/reality/tables (was MetadataEtc: every load scanned 21 paks)
TRAIT_RECORD = 0x68
STATS = ["Combat", "Exploration", "Mining", "Diplomatic", "FuelBurnRate", "FuelCapacity", "Speed", "ExtraLoot",
         "Repair", "Invulnerable", "Stealth"]
STRENGTHS = ["NegativeLarge", "NegativeMedium", "NegativeSmall", "TertiarySmall", "TertiaryMedium", "TertiaryLarge",
             "SecondarySmall", "SecondaryMedium", "SecondaryLarge", "Primary"]
CLASS_LABELS = {"Combat": "Combat", "Exploration": "Exploration", "Mining": "Industrial", "Diplomacy": "Trade",
                "Support": "Support", "Normandy": "Normandy", "DeepSpace": "Living", "DeepSpaceCommon": "Living",
                "Pirate": "Pirate", "GhostShip": "Ghost ship", "Swarm": "Swarm"}
# Icon of each class / of each stat on the fleet screen (gamedata.EXTRA_ICONS).
CLASS_ICONS = {"Combat": "combat", "Exploration": "exploration", "Mining": "industrial", "Diplomacy": "diplomatic",
               "Support": "frigate"}
STAT_ICONS = {"Combat": "combat", "Exploration": "explore", "Mining": "mining", "Diplomatic": "trading",
              "FuelBurnRate": "fuel", "FuelCapacity": "fuel", "Speed": "speed", "ExtraLoot": "salvage",
              "Repair": "repair", "Invulnerable": "invulnerable", "Stealth": "special"}


def class_icon_id(frigate_class: str | None) -> str:
    return f"FRIGATE_CLASS_{CLASS_ICONS.get(frigate_class or '', 'frigate').upper()}"


def trait_icon_id(stat: str, negative: bool) -> str:
    return f"FRIGATE_TRAIT_{'NEGATIVE' if negative else 'PRIMARY'}_{STAT_ICONS.get(stat, 'special').upper()}"


def icon_textures() -> dict[str, str]:
    """{icon id: texture} for gamedata.EXTRA_ICONS."""
    out = {f"FRIGATE_CLASS_{name.upper()}": (f"TEXTURES/UI/FRONTEND/ICONS/FLEET/FRIGATE/FRIGATE.{name.upper()}.DDS"
                                             if name != "frigate" else "TEXTURES/UI/FRONTEND/ICONS/FLEET/FRIGATE/FRIGATE.DDS")
           for name in set(CLASS_ICONS.values())}
    for name in set(STAT_ICONS.values()):
        for kind in ("PRIMARY", "NEGATIVE"):
            out[f"FRIGATE_TRAIT_{kind}_{name.upper()}"] = f"TEXTURES/UI/FRONTEND/ICONS/FLEET/PROPERTY/PROPERTY.{kind}.{name.upper()}.DDS"
    return out


def parse_traits(data: bytes) -> dict[str, dict]:
    """frigatetraittable.mbin -> {trait id: {name (text key), stat, strength}}; {} when the layout is not the expected one."""
    try:
        start, count = mbin.root_list(data)
        if mbin.record_size(data, start, count) != TRAIT_RECORD:
            return {}
        out = {}
        for k in range(count):
            p = start + k * TRAIT_RECORD
            trait_id = mbin.fixed_str(data, p + 0x20, 0x10)
            stat, strength = struct.unpack_from("<2I", data, p + 0x5C)
            if trait_id and stat < len(STATS) and strength < len(STRENGTHS):
                out[trait_id] = {"name": mbin.fixed_str(data, p, 0x20), "stat": STATS[stat], "strength": STRENGTHS[strength]}
    except (struct.error, mbin.MbinError, IndexError):
        return {}
    named = sum(1 for t in out.values() if (t["name"] or "").startswith(("FLEET_TRAIT", "UI_")))   # UI_NORMANDY_TRAIT1 ...
    return out if out and named >= len(out) * 0.8 else {}


def load_traits(install) -> dict:
    """{traits: {...}, source, error?}: the installed game's frigate traits (empty on failure: ids are shown then)."""
    from .hgpak import PakError, PakSet, ZstdUnavailable
    if install is None:
        return {"traits": {}, "source": "none", "error": "game installation not found"}
    try:
        with PakSet(install.pcbanks, {TRAIT_FILE: TRAIT_PAK}) as paks:
            traits = parse_traits(paks.read(TRAIT_FILE))
    except (KeyError, OSError, PakError, ZstdUnavailable) as exc:
        return {"traits": {}, "source": "none", "error": f"{type(exc).__name__}: {exc}"}
    if not traits:
        return {"traits": {}, "source": "none", "error": "the game's frigate trait table changed layout"}
    return {"traits": traits, "source": "game files"}


def _enum(value, field: str) -> str | None:
    return (value or {}).get(field) if isinstance(value, dict) else None


def frigates_from_save(readable: dict) -> list[dict]:
    """Your frigates from FleetFrigates: class, race, grade, stats, traits, record, home system, state."""
    ps = ((readable or {}).get("BaseContext") or {}).get("PlayerStateData") or {}
    out_on = {i for e in ps.get("FleetExpeditions") or [] if isinstance(e, dict) for i in e.get("AllFrigateIndices") or []}
    out = []
    for i, f in enumerate(ps.get("FleetFrigates") or []):
        if not isinstance(f, dict):
            continue
        stats = [int(v) for v in (f.get("Stats") or [])[:len(STATS)]]
        home = (f.get("HomeSystemSeed") or [None, None])
        try:
            home_key = int(home[1], 16) if isinstance(home, list) and len(home) > 1 and home[0] else None
        except (TypeError, ValueError):
            home_key = None
        out.append({
            "index": i, "name": f.get("CustomName") or "", "class": _enum(f.get("FrigateClass"), "FrigateClass"),
            "race": _enum(f.get("Race"), "AlienRace"), "grade": _enum(f.get("InventoryClass"), "InventoryClass") or "?",
            "stats": dict(zip(STATS, stats)), "traits": [str(t).lstrip("^") for t in f.get("TraitIDs") or [] if str(t).lstrip("^")],
            "expeditions": int(f.get("TotalNumberOfExpeditions") or 0),
            "successes": int(f.get("TotalNumberOfSuccessfulEvents") or 0),
            "failures": int(f.get("TotalNumberOfFailedEvents") or 0),
            "damaged": int(f.get("DamageTaken") or 0) > 0, "times_damaged": int(f.get("NumberOfTimesDamaged") or 0),
            "home": home_key, "on_expedition": i in out_on,
        })
    return out


def text_keys(items: list[dict], traits: dict) -> set[str]:
    return {traits[t]["name"] for f in items for t in f["traits"] if t in traits and traits[t]["name"]}


def frigate_label(f: dict) -> str:
    return f["name"] or f"{CLASS_LABELS.get(f['class'], f['class'] or 'Frigate')} frigate"


def _icon(texts, cell, icon_id: str):
    gamedata = getattr(texts, "gamedata", None)
    icon = gamedata.icon_name(icon_id) if gamedata is not None and hasattr(gamedata, "icon_name") else None
    if not icon:
        return cell
    return {**cell, "icon": icon} if isinstance(cell, dict) else {"text": cell, "icon": icon}


def _trait_text(trait_id: str, traits: dict, texts) -> str:
    t = traits.get(trait_id)
    if not t:
        return trait_id
    name = texts.key(t["name"]) if hasattr(texts, "key") else None
    name = name if name and name != t["name"] else trait_id
    kind = "negative" if t["strength"].startswith("Negative") else "primary" if t["strength"] == "Primary" else ""
    return f"{name} ({kind})" if kind else name


def frigate_sections(items: list[dict], traits: dict, texts, system_label) -> list[dict]:
    """The frigate table (class icon, grade, race, stats, traits, record, home, state). `system_label(key)` names a
    system key, or returns None for an unknown one."""
    if not items:
        return [{"type": "text", "text": "No frigates in this save."}]
    rows = []
    for f in items:
        main = next((t for t in f["traits"] if traits.get(t, {}).get("strength") == "Primary"), None)
        cell = {"text": frigate_label(f)}
        trait_lines = "\n".join(_trait_text(t, traits, texts) for t in f["traits"])
        if trait_lines:
            cell["hint"] = f"Traits:\n{trait_lines}"
        cell = _icon(texts, cell, class_icon_id(f["class"]))
        events = f["successes"] + f["failures"]
        record = f"{f['expeditions']} expeditions" + (f", {round(100 * f['successes'] / events)} % of events won" if events else "")
        state = "on an expedition" if f["on_expedition"] else "damaged - repair it" if f["damaged"] else "ready"
        traits_cell = ", ".join(_trait_text(t, traits, texts) for t in f["traits"]) or None
        if main and traits_cell:
            traits_cell = _icon(texts, {"text": traits_cell}, trait_icon_id(traits[main]["stat"], False))
        home = system_label(f["home"]) if f["home"] is not None else None
        rows.append([cell, CLASS_LABELS.get(f["class"], f["class"]), f["grade"], f["race"],
                     f["stats"].get("Combat"), f["stats"].get("Exploration"), f["stats"].get("Mining"),
                     f["stats"].get("Diplomatic"), traits_cell, record, home, state])
    return [{"type": "table", "id": "frigates", "title": f"Frigates ({len(items)})",
             "columns": ["Frigate", "Class", "Grade", "Race", "Combat", "Exploration", "Industry", "Trade", "Traits",
                         "Record", "Bought in", "State"],
             "rows": rows}]
