"""Your equipment from the save: exosuit, multi-tools, exocraft and the freighter's technology.

Technology lives in inventory slots of type Technology (``Amount`` = the charge, -1 for technology that needs
none):

* exosuit: ``Inventory_TechOnly`` (and ``Inventory``);
* multi-tools: ``Multitools[i].Store`` with ``Name`` and ``Store.Class``; unused entries have no ``Resource``
  model; ``ActiveMultioolIndex`` - spelled so in the save - is the one in your hand;
* exocraft: ``VehicleOwnership[i].Inventory_TechOnly``, indexed by GcVehicleType (Buggy = Roamer, Bike = Nomad,
  Truck = Colossus, WheeledBike = Pilgrim, Hovercraft - unused by the game -, Submarine = Nautilon, Mech =
  Minotaur), named by the game's ``VEHICLE_<TYPE>_TITLE_L``. The save keeps an entry for every type whether you
  built it or not, so an exocraft is listed when it carries technology; ``PrimaryVehicle`` is the one you summon;
* freighter: ``FreighterInventory_TechOnly`` (and ``FreighterInventory``).

Procedural upgrades (``UP_LASER1#53433``) are named and iconised through their template like inventory items; what
a part does (its stat modifiers) comes from techstats via ``Texts.modifiers``.
Read 2026-10-05: 19 exosuit parts, 6 multi-tools (2 in use), Roamer with 10 parts, Minotaur with 4.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# GcVehicleType order (libMBIN 7.04) -> the game's name key; None = not an exocraft the game offers.
VEHICLE_KEYS = ("VEHICLE_BUGGY_TITLE_L", "VEHICLE_BIKE_TITLE_L", "VEHICLE_TRUCK_TITLE_L",
                "VEHICLE_WHEELEDBIKE_TITLE_L", None, "VEHICLE_SUBMARINE_TITLE_L", "VEHICLE_MECH_TITLE_L")
VEHICLE_FALLBACK = ("Roamer", "Nomad", "Colossus", "Pilgrim", None, "Nautilon", "Minotaur")
DAMAGED_PREFIX = "SHIPSLOT_DMG"    # a damaged ship slot shows as this technology until it is repaired
COLUMNS = ["Technology", "Category", "Charge", "What it does (possible range)"]


def technology_in(*inventories) -> list[dict]:
    """[{id, charge, max}] of the Technology slots of these inventories (None entries are skipped)."""
    out = []
    for inventory in inventories:
        for slot in ((inventory or {}).get("Slots") or []):
            if ((slot.get("Type") or {}).get("InventoryType")) != "Technology" or not slot.get("Id"):
                continue
            out.append({"id": str(slot["Id"]).lstrip("^"), "charge": slot.get("Amount"), "max": slot.get("MaxAmount")})
    return out


def charge_text(tech: dict) -> str | None:
    """'42 / 100', '42' without a maximum, None for technology that holds no charge."""
    if tech.get("charge") is None or tech["charge"] < 0:
        return None
    return f"{tech['charge']} / {tech['max']}" if tech.get("max") else str(tech["charge"])


def technology_table(technology: list[dict], texts, title: str, table_id: str | None = None,
                     extra=None) -> dict:
    """One table of installed technology: name (icon, tooltip with the game's description), category, charge and
    what it does. ``extra(tech id) -> str | None`` adds a note to the last column (ships: star colours a drive
    opens). Damaged ship slots are left out."""
    rows = []
    for tech in technology:
        if tech["id"].startswith(DAMAGED_PREFIX):
            continue
        does = "; ".join(texts.modifiers(tech["id"])) if hasattr(texts, "modifiers") else ""
        note = extra(tech["id"]) if extra else None
        does = "; ".join(p for p in (does, note) if p) or None
        rows.append([texts.item(tech["id"]), texts.category(tech["id"]), charge_text(tech), does])
    table = {"type": "table", "title": title, "columns": COLUMNS, "rows": rows, "empty": "No technology installed."}
    if table_id:
        table["id"] = table_id
    return table


RANGE_NOTE = ("Hover a technology for the game's description. Charge is what it holds now; upgrades and passive "
              "parts need none. For procedural upgrades (B/A/S-class modules) the last column lists every stat the "
              "module can have, with its range: the game draws the module's stats and exact values from its seed and "
              "keeps the result to itself.")


@dataclass
class Loadout:
    """Something that carries technology: the exosuit, a multi-tool, an exocraft, the freighter."""
    title: str                        # English name (exocraft: used when the game's text is not resolved)
    technology: list[dict]
    table_id: str | None = None
    active: bool = False              # the multi-tool in your hand / the exocraft you summon
    name_key: str | None = None       # the game's localisation key of the name (exocraft)
    note: str = ""                    # appended to the name (" (summoned first)")

    @property
    def ids(self) -> list[str]:
        return [t["id"] for t in self.technology]

    def name(self, texts=None) -> str:
        """The name in the player's languages when the game's text is known ('Roamer'), with its note."""
        label = texts.label(self.name_key) if self.name_key and hasattr(texts, "label") else None
        return (label or self.title) + self.note


@dataclass
class Equipment:
    """Your equipment read from one save (``from_save``), shown as the Inventory -> Equipment tab (``sections``)."""
    exosuit: Loadout = field(default_factory=lambda: Loadout("Exosuit technology", [], "exosuit-tech"))
    multitools: list[Loadout] = field(default_factory=list)
    exocraft: list[Loadout] = field(default_factory=list)
    freighter: Loadout = field(default_factory=lambda: Loadout("Freighter technology", [], "freighter-tech"))

    @classmethod
    def from_save(cls, readable: dict) -> Equipment:
        """Read the exosuit, multi-tools (in your hand first), exocraft that carry technology and the freighter."""
        ps = ((readable or {}).get("BaseContext") or {}).get("PlayerStateData") or {}
        active = ps.get("ActiveMultioolIndex", ps.get("ActiveMultitoolIndex"))
        tools = []
        for i, tool in enumerate(ps.get("Multitools") or []):
            if not isinstance(tool, dict) or not ((tool.get("Resource") or {}).get("Filename")):
                continue
            store = tool.get("Store") or {}
            name = tool.get("Name") or "(unnamed multi-tool)"
            klass = ((store.get("Class") or {}).get("InventoryClass")) or "?"
            tools.append(Loadout(f"{name} (class {klass}{', in your hand' if i == active else ''})",
                                 technology_in(store), active=i == active))
        tools.sort(key=lambda t: not t.active)
        craft = []
        primary = ps.get("PrimaryVehicle")
        for i, vehicle in enumerate(ps.get("VehicleOwnership") or []):
            if i >= len(VEHICLE_KEYS) or VEHICLE_KEYS[i] is None or not isinstance(vehicle, dict):
                continue
            tech = technology_in(vehicle.get("Inventory_TechOnly"), vehicle.get("Inventory"))
            if tech:
                craft.append(Loadout(VEHICLE_FALLBACK[i], tech, active=i == primary, name_key=VEHICLE_KEYS[i],
                                     note=" (summoned first)" if i == primary else ""))
        return cls(exosuit=Loadout("Exosuit technology", technology_in(ps.get("Inventory_TechOnly"), ps.get("Inventory")),
                                   "exosuit-tech"),
                   multitools=tools, exocraft=craft,
                   freighter=Loadout("Freighter technology", technology_in(ps.get("FreighterInventory_TechOnly"),
                                                                           ps.get("FreighterInventory")), "freighter-tech"))

    def loadouts(self) -> list[Loadout]:
        return [self.exosuit, *self.multitools, *self.exocraft, self.freighter]

    def item_ids(self) -> list[str]:
        """Every technology id shown (to convert their icons)."""
        return list(dict.fromkeys(i for loadout in self.loadouts() for i in loadout.ids))

    def sections(self, texts) -> list[dict]:
        """The Equipment tab: sub-tabs Exosuit / Multi-tools (the one in your hand first) / Exocraft / Freighter."""
        def tab(tab_id, label, sections, count=None):
            return {"id": tab_id, "label": label, "badge": count or None, "sections": sections}

        def own(loadout):
            return technology_table(loadout.technology, texts, f"{loadout.name(texts)} ({len(loadout.technology)})",
                                    loadout.table_id)

        tools = [technology_table(t.technology, texts, f"Multi-tool: {t.name(texts)}") for t in self.multitools]
        craft = [technology_table(c.technology, texts, f"Exocraft: {c.name(texts)}") for c in self.exocraft]
        return [{"type": "tabs", "id": "equipment-tabs", "tabs": [
            tab("exosuit", "Exosuit", [own(self.exosuit)], len(self.exosuit.technology)),
            tab("multitools", "Multi-tools", tools or [{"type": "text", "text": "No multi-tool in this save."}],
                len(self.multitools)),
            tab("exocraft", "Exocraft", craft or [{"type": "text", "text": "No exocraft carries technology yet."}],
                len(self.exocraft)),
            tab("freighter", "Freighter", [own(self.freighter)], len(self.freighter.technology)),
        ]}, {"type": "text", "text": RANGE_NOTE}]


def equipment_sections(equipment: Equipment | None, texts) -> list[dict]:
    """The Equipment tab, or a note until a save has been read."""
    if equipment is None:
        return [{"type": "text", "text": "Equipment appears once a save has been read."}]
    return equipment.sections(texts)
