"""Copying any one inventory or loadout - the generalisation of the ship and container exports.

Right-click a table in the *Inventory* tab (exosuit, starship, freighter) or any technology table (exosuit,
multi-tool, exocraft, freighter, each ship under *Ships & bases*) and copy what it holds as TOON or JSON - the
formats `ships.py` and `container_export.py` write. As there, the text is the action's `copy` (app 3.18.0 puts
it on the clipboard) and is kept on the page as well (`export_section`), because a browser outside a secure
context refuses the clipboard.

A *place* is one such table: an inventory (stacks of items) or a loadout (installed technology). Its `key` is
what the row menu hands back, so it has to be stable and is matched exactly (untrusted input):

* ``exosuit`` - the exosuit's inventory and its cargo; ``exosuit-tech`` its technology;
* ``ship-<save index>`` - that starship's cargo; ``ship-<save index>-tech`` its technology;
* ``freighter`` / ``freighter-tech``; ``multitool-<save index>-tech``; ``exocraft-<save index>-tech``.

Storage containers keep their own module (`container_export`): they are copied one or all at a time and have a
menu of their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .container_export import item_rows

EXPORT_TOON = "export_place_toon"
EXPORT_JSON = "export_place_json"
EXPORT_ALL_TOON = "export_places_toon"
EXPORT_ALL_JSON = "export_places_json"
EXPORT_ACTIONS = (EXPORT_TOON, EXPORT_JSON, EXPORT_ALL_TOON, EXPORT_ALL_JSON)
ALL_ACTIONS = (EXPORT_ALL_TOON, EXPORT_ALL_JSON)
JSON_ACTIONS = (EXPORT_JSON, EXPORT_ALL_JSON)
EXPORT_ID = "place-export"              # the section the copied text is also shown in (Inventory tab)
FLEET_EXPORT_ID = "ship-place-export"   # the same text under Ships & bases (a ship's technology)

INVENTORY = "inventory"
TECHNOLOGY = "technology"

MENU = [
    {"id": EXPORT_TOON, "label": "Copy this table (TOON)",
     "description": "Everything this inventory or loadout holds as TOON, a compact form for pasting into a prompt."},
    {"id": EXPORT_JSON, "label": "Copy this table (JSON)",
     "description": "The same data as JSON, for a script rather than a prompt."},
    {"id": EXPORT_ALL_TOON, "label": "Copy every inventory and loadout (TOON)",
     "description": "Exosuit, every starship, the freighter, every multi-tool and exocraft - inventories and "
                    "installed technology - one after another, as TOON."},
    {"id": EXPORT_ALL_JSON, "label": "Copy every inventory and loadout (JSON)",
     "description": "The same as JSON."},
]
ROW_HINT = "Right-click to copy this table, or every inventory and loadout, as TOON or JSON."


@dataclass
class Place:
    """One table that can be copied: an inventory (`rows`) or a loadout (`technology`)."""
    key: str
    label: str
    kind: str                                   # INVENTORY | TECHNOLOGY
    rows: list = field(default_factory=list)        # inventory: [(item id, amount, max)]
    technology: list = field(default_factory=list)  # loadout: [{id, charge, max}] as equipment.technology_in gives


def section_id(key: str) -> str:
    """Which export section a copy of this place should scroll to. A ship's technology table lives under
    *Ships & bases*, every other place under *Inventory* - and the app opens the tabs holding the section it
    is told to focus, so naming the wrong one drags the user into another tab."""
    clean = str(key or "").strip()
    return FLEET_EXPORT_ID if clean.startswith("ship-") and clean.endswith("-tech") else EXPORT_ID


def menu_keys(key: str, count: int) -> dict:
    """The copy menu on a table that stands for this one place: every row carries the same key, so a
    right-click anywhere in it copies the whole table (`count` = how many rows it has).

    No `row_action`: the rows are items, not places, so a left click must not copy the table by accident."""
    return {"row_keys": [key] * max(int(count or 0), 1), "row_menu": MENU, "row_hint": ROW_HINT}


def loadout_menu(loadout) -> dict:
    """The copy menu of an `equipment.Loadout`'s technology table."""
    return menu_keys(loadout.key, len(loadout.technology))


def ship_tech_menu(ship: dict) -> dict:
    """The copy menu of one ship's technology table (the Ships & bases tab)."""
    return menu_keys(ship_key(ship, tech=True), len(ship.get("technology") or []))


def ship_key(ship: dict, tech: bool = False) -> str:
    """The place key of a ship's cargo (`ship-0`) or of its technology (`ship-0-tech`), from the ship's index
    in the save - the only id of a ship that never changes (a ship can be renamed)."""
    return f"ship-{ship.get('index')}" + ("-tech" if tech else "")


def ship_place_label(ship: dict) -> str:
    """'Starship inventory: Mad Falcon' - the name the Inventory tab shows, never empty."""
    name = ship.get("name") or f"(unnamed {ship.get('type') or ship.get('class') or 'ship'})"
    return f"Starship inventory: {name}"


def inventory_places(snap: dict | None, ships: list[dict] | None = None) -> list[Place]:
    """The inventories of a snapshot: exosuit (with its cargo), every starship, the freighter."""
    snap = snap or {}
    out = [Place("exosuit", "Exosuit inventory", INVENTORY,
                 list(snap.get("exosuit") or []) + list(snap.get("exosuit_cargo") or []))]
    by_index = {s.get("index"): s for s in (ships or [])}
    for ship in snap.get("ships") or []:
        known = by_index.get(ship.get("index")) or ship
        out.append(Place(ship_key(ship), ship_place_label(known), INVENTORY, ship.get("inventory") or []))
    freighter = snap.get("freighter") or {}
    name = freighter.get("name")
    out.append(Place("freighter", f"Freighter inventory{f': {name}' if name else ''}", INVENTORY,
                     freighter.get("inventory") or []))
    return out


def technology_places(ships: list[dict] | None, eq, texts=None) -> list[Place]:
    """The loadouts: every ship's technology (`ships` as `ships.ships_from_save` gives them) and the exosuit,
    multi-tools, exocraft and freighter of an `equipment.Equipment` (None for either leaves it out)."""
    from .ships import ship_label
    out = []
    for ship in ships or []:
        out.append(Place(ship_key(ship, tech=True), f"Technology of {ship_label(ship)}", TECHNOLOGY,
                         technology=ship.get("technology") or []))
    for loadout in (eq.loadouts() if eq is not None else []):
        out.append(Place(loadout.key, loadout.name(texts), TECHNOLOGY, technology=loadout.technology))
    return out


def places(snap: dict | None, ships: list[dict] | None = None, eq=None, texts=None) -> list[Place]:
    """Every place that can be copied, in the order the page shows them."""
    return inventory_places(snap, ships) + technology_places(ships, eq, texts)


def find(all_places: list[Place], key) -> Place | None:
    """The place with this key, as a row menu hands it back - untrusted, so only an exact match counts."""
    wanted = str(key or "").strip()
    return next((p for p in all_places if p.key == wanted), None)


def technology_data(technology: list[dict], texts) -> list[dict]:
    """Installed technology as plain data, in the shape the ship export writes (same keys on every row, so
    TOON saves them as one header plus bare rows).

    The id is the table id without the seed (`UP_HYP4#66014` -> `UP_HYP4`, as the ship export writes it), while
    the *name* is looked up from the raw id - that is what resolves a procedural upgrade's name."""
    from .equipment import DAMAGED_PREFIX
    from .ships import tech_id
    out = []
    for tech in technology:
        charge = tech.get("charge")
        out.append({"id": tech_id(tech["id"]), "name": texts.name(tech["id"]) or tech_id(tech["id"]),
                    "category": texts.category(tech["id"]) if hasattr(texts, "category") else None,
                    "charge": charge if (charge or -1) >= 0 else None, "max_charge": tech.get("max") or None,
                    "damaged": str(tech["id"]).startswith(DAMAGED_PREFIX)})
    return out


def place_data(place: Place, texts, lookup) -> dict:
    """One place as plain data: an inventory's stacks with their base value, or a loadout's technology."""
    base = {"place": place.label, "key": place.key, "kind": place.kind}
    if place.kind == TECHNOLOGY:
        rows = technology_data(place.technology, texts)
        return {**base, "installed": len(rows), "technology": rows}
    items = item_rows(place.rows, texts, lookup)
    worth = [i["value_stack"] for i in items if i["value_stack"]]
    return {**base, "stacks": len(items), "value_total": sum(worth) if worth else None, "items": items}


def all_data(all_places: list[Place], texts, lookup) -> dict:
    """Every place that holds something, and the names of the empty ones."""
    full = [p for p in all_places if (p.technology if p.kind == TECHNOLOGY else p.rows)]
    return {"places": [place_data(p, texts, lookup) for p in full],
            "empty": [p.label for p in all_places if p not in full]}


def entries(data: dict) -> int:
    """How many stacks or technologies an export holds - what its message reports."""
    if "places" in data:
        return sum(p.get("stacks", p.get("installed", 0)) for p in data["places"])
    return data.get("stacks", data.get("installed", 0))


def export_section(state: dict | None, as_id: str = EXPORT_ID) -> list[dict]:
    """The last copied inventory/loadout export, shown on the page as well as put on the clipboard.

    A browser only reaches the clipboard in a secure context (localhost or the tunnel), and the standalone host
    can be opened over a plain LAN address - so the text is always on the page too, to select by hand."""
    if not state:
        return []
    return [{"type": "text", "id": as_id,
             "title": f"{state['what']} as {state['format']} - {state['chars']:,} characters",
             "text": state["text"]}]
