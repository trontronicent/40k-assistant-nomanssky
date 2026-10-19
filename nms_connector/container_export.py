"""Copying storage container contents for a prompt or a script - the container counterpart of the ship export.

Right-click a container (in the *Storage* tab's overview, or any item row of its table) and copy that one
container, or every container, as TOON or JSON - the formats the ship export writes. As there, the text is
the action's `copy` (app 3.18.0 puts it on the clipboard) and is also kept on the page (`export_section`),
because a browser outside a secure context refuses the clipboard.

Every item row carries the same keys, so TOON writes each container's items as one header plus bare rows
(`toon.table_fields`) - the shape it saves on.
"""

from __future__ import annotations

EXPORT_TOON = "export_container_toon"
EXPORT_JSON = "export_container_json"
EXPORT_ALL_TOON = "export_containers_toon"
EXPORT_ALL_JSON = "export_containers_json"
EXPORT_ACTIONS = (EXPORT_TOON, EXPORT_JSON, EXPORT_ALL_TOON, EXPORT_ALL_JSON)
ALL_ACTIONS = (EXPORT_ALL_TOON, EXPORT_ALL_JSON)
JSON_ACTIONS = (EXPORT_JSON, EXPORT_ALL_JSON)
EXPORT_ID = "container-export"          # the section the copied text is also shown in
OVERVIEW_ID = "storage-overview"

MENU = [
    {"id": EXPORT_TOON, "label": "Copy this container (TOON)",
     "description": "Every stack of this container - name, id, amount, stack limit and base value - as TOON, "
                    "a compact form for pasting into a prompt."},
    {"id": EXPORT_JSON, "label": "Copy this container (JSON)",
     "description": "The same data as JSON, for a script rather than a prompt."},
    {"id": EXPORT_ALL_TOON, "label": "Copy all containers (TOON)",
     "description": "Every storage container that holds something, one after another, as TOON."},
    {"id": EXPORT_ALL_JSON, "label": "Copy all containers (JSON)",
     "description": "Every storage container that holds something, as JSON."},
]
ROW_HINT = "Right-click a container to copy it or all of them (left click copies this one as TOON)."


def label(chest: dict) -> str:
    """'Storage Container 3: Ores' for the game's numbered containers (a custom name only - the game's default
    BLD_* key is no name), 'Other storage (CorvetteStorage)' for the rest."""
    if chest["number"] is None:
        return f"Other storage ({chest['key'].removesuffix('Inventory')})"
    custom = chest["name"] if chest["name"] and not str(chest["name"]).startswith("BLD_") else None
    return f"Storage Container {chest['number']}" + (f": {custom}" if custom else "")


def find(storage: list[dict], key) -> dict | None:
    """The container with this save key (`Chest4Inventory`), as a row key hands it back - untrusted, so only
    an exact match counts."""
    return next((c for c in storage if c["key"] == str(key or "").strip()), None)


def container_data(chest: dict, texts, lookup) -> dict:
    """One container as plain data: its name, number and every stack with its base value (None where the game
    gives the item none, never a wrong 0)."""
    items = []
    for item_id, amount, maximum in chest["rows"]:
        unit = (lookup(item_id) or {}).get("value")
        items.append({"id": str(item_id), "name": texts.name(item_id) or str(item_id), "amount": int(amount or 0),
                      "max": maximum or None, "value_each": unit or None,
                      "value_stack": unit * amount if unit and isinstance(amount, int) else None})
    worth = [i["value_stack"] for i in items if i["value_stack"]]
    return {"container": label(chest), "number": chest["number"], "key": chest["key"], "stacks": len(items),
            "value_total": sum(worth) if worth else None, "items": items}


def all_data(storage: list[dict], texts, lookup) -> dict:
    """Every container that holds something, and the numbers of the empty ones."""
    full = [c for c in storage if c["rows"]]
    return {"containers": [container_data(c, texts, lookup) for c in full],
            "empty": [c["number"] for c in storage if not c["rows"] and c["number"] is not None]}


def overview_section(storage: list[dict], lookup) -> dict | None:
    """The Storage tab's overview: one row per container that holds something, with the copy menu (its keys are
    the containers' save keys). None when nothing is stored."""
    full = [c for c in storage if c["rows"]]
    if not full:
        return None
    rows = []
    for chest in full:
        values = [(lookup(i) or {}).get("value") for i, _a, _m in chest["rows"]]
        worth = sum(v * a for v, (_i, a, _m) in zip(values, chest["rows"], strict=True) if v and isinstance(a, int))
        rows.append([label(chest), len(chest["rows"]), sum(int(a or 0) for _i, a, _m in chest["rows"]), worth or None])
    return {"type": "table", "id": OVERVIEW_ID, "title": f"Containers ({len(full)})",
            "columns": ["Container", "Stacks", "Items", "Value (base)"], "rows": rows,
            **menu_keys([c["key"] for c in full]), "row_action": EXPORT_TOON, "row_hint": ROW_HINT}


def menu_keys(keys: list[str]) -> dict:
    """The copy menu on a table whose rows stand for these containers (one save key per row)."""
    return {"row_keys": keys, "row_menu": MENU}


def export_section(state: dict | None) -> list[dict]:
    """The last copied container export, shown on the page as well as put on the clipboard."""
    if not state:
        return []
    return [{"type": "text", "id": EXPORT_ID,
             "title": f"{state['what']} as {state['format']} - {state['chars']:,} characters",
             "text": state["text"]}]
