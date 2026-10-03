"""Turn a de-obfuscated save into the facts a companion needs (pure functions).

Every accessor is defensive: a field missing after a game update yields None or
an empty list instead of an exception, so one renamed key never blanks the view.
"""

from __future__ import annotations

from datetime import datetime, timezone

# The first galaxies by RealityIndex; later ones are shown as "Galaxy #n".
GALAXIES = ["Euclid", "Hilbert Dimension", "Calypso", "Hesperius Dimension", "Hyades",
            "Ickjamatew", "Budullangr", "Kikolgallr", "Eltiensleen", "Eissentam"]

# Ship class from the model folder in Resource.Filename.
SHIP_CLASSES = {"FIGHTERS": "Fighter", "DROPSHIPS": "Hauler", "SCIENTIFIC": "Explorer", "SHUTTLE": "Shuttle",
                "SAILSHIP": "Solar", "BIOPARTS": "Living Ship", "S-CLASS": "Living Ship",
                "SENTINELSHIP": "Interceptor", "ROYAL": "Exotic", "CORVETTE": "Corvette"}

BASE_TYPES = {"HomePlanetBase": "Planet base", "FreighterBase": "Freighter base",
              "ExternalPlanetBase": "Other base (settlement)"}


def _get(d, *path, default=None):
    for key in path:
        if not isinstance(d, dict) or key not in d:
            return default
        d = d[key]
    return d


def galaxy_name(reality_index) -> str:
    if isinstance(reality_index, int) and 0 <= reality_index < len(GALAXIES):
        return GALAXIES[reality_index]
    return f"Galaxy #{reality_index + 1}" if isinstance(reality_index, int) else "unknown"


def portal_code(planet: int, system: int, y: int, z: int, x: int) -> str:
    """The 12 portal glyphs as hex digits: planet, system (3), Y (2), Z (3), X (3)."""
    return f"{planet & 0xF:X}{system & 0xFFF:03X}{y & 0xFF:02X}{z & 0xFFF:03X}{x & 0xFFF:03X}"


def _signed(value: int, bits: int) -> int:
    return value - (1 << bits) if value >= (1 << (bits - 1)) else value


def unpack_address(value) -> dict | None:
    """Decode a packed galactic address (int, or a '0x…' string) used by bases."""
    if isinstance(value, str):
        try:
            value = int(value, 16)
        except ValueError:
            return None
    if not isinstance(value, int):
        return None
    return {"VoxelX": _signed(value & 0xFFF, 12), "VoxelZ": _signed((value >> 12) & 0xFFF, 12),
            "VoxelY": _signed((value >> 24) & 0xFF, 8), "RealityIndex": (value >> 32) & 0xFF,
            "SolarSystemIndex": (value >> 40) & 0xFFF, "PlanetIndex": (value >> 52) & 0xF}


def address_portal(addr: dict) -> str | None:
    try:
        return portal_code(addr["PlanetIndex"], addr["SolarSystemIndex"], addr["VoxelY"], addr["VoxelZ"], addr["VoxelX"])
    except (KeyError, TypeError):
        return None


def item_name(item_id) -> str:
    """'^CATALYST1' → 'CATALYST1' (display names live in game data, not in the save)."""
    return item_id[1:] if isinstance(item_id, str) and item_id.startswith("^") else str(item_id)


def inventory_rows(inventory) -> list[list]:
    """[[item, amount, max], ...] for the occupied slots, largest stacks first."""
    rows = []
    for slot in _get(inventory, "Slots", default=[]) or []:
        if not isinstance(slot, dict) or not slot.get("Id"):
            continue
        kind = _get(slot, "Type", "InventoryType", default="")
        if kind == "Technology":
            continue  # installed tech, not cargo
        rows.append([item_name(slot["Id"]), slot.get("Amount"), slot.get("MaxAmount")])
    return sorted(rows, key=lambda r: (-(r[1] or 0), r[0]))


def ship_class(filename) -> str:
    parts = str(filename or "").upper().split("/")
    for part in parts:
        if part in SHIP_CLASSES:
            return SHIP_CLASSES[part]
    return parts[-1].split(".")[0].title() if parts and parts[-1] else "unknown"


def summarize(save: dict) -> dict:
    """The connector's snapshot of one save."""
    ps = _get(save, "BaseContext", "PlayerStateData", default={}) or {}
    common = _get(save, "CommonStateData", default={}) or {}
    ua = ps.get("UniverseAddress") or {}
    ga = ua.get("GalacticAddress") or {}
    stamp = ps.get("TimeStamp")

    ships = []
    for i, ship in enumerate(ps.get("ShipOwnership") or []):
        filename = _get(ship, "Resource", "Filename", default="")
        if not filename:
            continue  # unused ship slot
        ships.append({"index": i, "name": ship.get("Name") or "(unnamed)", "class": ship_class(filename),
                      "primary": i == ps.get("PrimaryShip"), "inventory": inventory_rows(ship.get("Inventory"))})

    bases = []
    for base in ps.get("PersistentPlayerBases") or []:
        addr = unpack_address(base.get("GalacticAddress")) or {}
        kind = _get(base, "BaseType", "PersistentBaseTypes", default="")
        bases.append({"name": base.get("Name") or "(unnamed)", "type": BASE_TYPES.get(kind, kind or "unknown"),
                      "galaxy": galaxy_name(addr.get("RealityIndex")), "portal": address_portal(addr) if addr else None,
                      "objects": len(base.get("Objects") or []),
                      "here": bool(addr) and addr.get("SolarSystemIndex") == ga.get("SolarSystemIndex")
                      and all(addr.get(k) == ga.get(k) for k in ("VoxelX", "VoxelY", "VoxelZ"))})

    return {
        "save_version": save.get("Version"),
        "save_name": common.get("SaveName") or None,
        "saved_at": datetime.fromtimestamp(stamp, timezone.utc).isoformat() if isinstance(stamp, int) and stamp > 0 else None,
        "play_time_s": common.get("TotalPlayTime"),
        "units": ps.get("Units"), "nanites": ps.get("Nanites"), "quicksilver": ps.get("Specials"),
        "health": ps.get("Health"), "shield": ps.get("Shield"), "ship_health": ps.get("ShipHealth"),
        "difficulty": _get(ps, "DifficultyState", "Preset", "DifficultyPresetType"),
        "location": {
            "galaxy": galaxy_name(ua.get("RealityIndex")),
            "voxel": [ga.get("VoxelX"), ga.get("VoxelY"), ga.get("VoxelZ")],
            "system_index": ga.get("SolarSystemIndex"), "planet_index": ga.get("PlanetIndex"),
            "portal": address_portal(ga),
            "position": (_get(save, "BaseContext", "SpawnStateData", "PlayerPositionInSystem") or [None] * 3)[:3],
        },
        "exosuit": inventory_rows(ps.get("Inventory")),
        "exosuit_cargo": inventory_rows(ps.get("Inventory_Cargo")),
        "freighter": {"name": ps.get("PlayerFreighterName") or None,
                      "inventory": inventory_rows(ps.get("FreighterInventory"))},
        "ships": ships,
        "bases": bases,
        "frigates": len(ps.get("FleetFrigates") or []),
        "expeditions": len(ps.get("FleetExpeditions") or []),
        "pets": len(ps.get("Pets") or []),
        "current_mission": item_name(ps.get("CurrentMissionID")) if ps.get("CurrentMissionID") else None,
    }
