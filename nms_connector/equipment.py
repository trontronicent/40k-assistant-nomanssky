"""Your equipment from the save: exosuit technology, multi-tools and the freighter's technology.

Technology lives in inventory slots of type Technology: the exosuit's in ``Inventory_TechOnly`` (and ``Inventory``),
each multi-tool's in ``Multitools[i].Store`` (``Name``, ``Store.Class``; unused entries have no ``Resource``
model and a zero seed; ``ActiveMultioolIndex`` - spelled so in the save - is the one in your hand), the
freighter's in ``FreighterInventory_TechOnly``. ``Amount`` is the charge, -1 for technology that needs none.
Procedural upgrades (``UP_LASER1#53433``) are named and iconised through their template like inventory items.
Read 2026-10-04: 19 exosuit parts, multi-tools "Shitttool" (B) and "Quantum Kay Needler" (A, 16 parts, active).
"""

from __future__ import annotations

from .ships import _technology


def _tech_of(*inventories) -> list[dict]:
    return _technology({"Inventory_TechOnly": inventories[0] or {}, "Inventory": (inventories[1] if len(inventories) > 1 else None) or {}})


def equipment_from_save(readable: dict) -> dict:
    """{exosuit: [tech], multitools: [{name, class, active, technology}], freighter: [tech]}."""
    ps = ((readable or {}).get("BaseContext") or {}).get("PlayerStateData") or {}
    active = ps.get("ActiveMultioolIndex", ps.get("ActiveMultitoolIndex"))
    tools = []
    for i, tool in enumerate(ps.get("Multitools") or []):
        if not isinstance(tool, dict) or not ((tool.get("Resource") or {}).get("Filename")):
            continue
        store = tool.get("Store") or {}
        tools.append({"name": tool.get("Name") or "", "class": ((store.get("Class") or {}).get("InventoryClass")) or "?",
                      "active": i == active, "technology": _tech_of(store, None),
                      "slots": len(store.get("ValidSlotIndices") or [])})
    tools.sort(key=lambda t: not t["active"])
    return {"exosuit": _tech_of(ps.get("Inventory_TechOnly"), ps.get("Inventory")),
            "multitools": tools,
            "freighter": _tech_of(ps.get("FreighterInventory_TechOnly"), ps.get("FreighterInventory"))}


def item_ids(equipment: dict) -> list[str]:
    """Every technology id shown (to convert their icons)."""
    ids = [t["id"] for t in equipment.get("exosuit") or []] + [t["id"] for t in equipment.get("freighter") or []]
    for tool in equipment.get("multitools") or []:
        ids += [t["id"] for t in tool["technology"]]
    return list(dict.fromkeys(ids))


def _charge(t: dict) -> str | None:
    if t.get("charge") is None or t["charge"] < 0:
        return None
    return f"{t['charge']} / {t['max']}" if t.get("max") else str(t["charge"])


def _rows(technology: list[dict], texts) -> list[list]:
    return [[texts.item(t["id"]), texts.category(t["id"]), _charge(t)] for t in technology]


COLUMNS = ["Technology", "Category", "Charge"]


def equipment_sections(equipment: dict | None, texts) -> list[dict]:
    """The Equipment tab: exosuit technology, each multi-tool (the one in your hand first), freighter technology."""
    if not equipment:
        return [{"type": "text", "text": "Equipment appears once a save has been read."}]
    out = [{"type": "table", "id": "exosuit-tech", "title": f"Exosuit technology ({len(equipment['exosuit'])})",
            "columns": COLUMNS, "rows": _rows(equipment["exosuit"], texts), "empty": "No technology installed."}]
    for tool in equipment["multitools"]:
        name = tool["name"] or "(unnamed multi-tool)"
        title = f"Multi-tool: {name} (class {tool['class']}{', in your hand' if tool['active'] else ''})"
        out.append({"type": "table", "title": title, "columns": COLUMNS, "rows": _rows(tool["technology"], texts),
                    "empty": "No technology installed."})
    if not equipment["multitools"]:
        out.append({"type": "text", "text": "No multi-tool in this save."})
    out.append({"type": "table", "id": "freighter-tech", "title": f"Freighter technology ({len(equipment['freighter'])})",
                "columns": COLUMNS, "rows": _rows(equipment["freighter"], texts), "empty": "No freighter technology."})
    out.append({"type": "text", "text": "Hover a technology for the game's description. Charge is what the technology "
                                        "holds now; upgrades and passive parts need none."})
    return out
