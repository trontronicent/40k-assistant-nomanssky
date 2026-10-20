"""The savegame editor's edit core: which containers a save has, what a change may be, and what it produces.

Pure throughout - a tree in, a new tree out - so every rule here is tested without a save file, a game or a
host. `save_write.py` turns a tree into bytes; the commit pipeline in `save_commit.py` is what writes.

Two things shape this module:

* It works on the **raw, obfuscated tree**, because `saves.deobfuscate` cannot be reversed (see
  `save_write.py`). `mapping.json` is read one way only, by `SaveKeys`, to find an obfuscated key by its
  readable name. Obfuscated keys are never written down here: they change with the game's version, and the
  mapping is the game's own answer for the version at hand.
* A refusal is a **sentence for the person who made the change**, returned rather than raised, the way
  `PluginSettings.update` answers the settings form. `apply` raises instead, because reaching it with an
  invalid change is a bug in the caller, not something a user did.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Where the player's state hangs. A normal save keeps it under BaseContext; an Expedition save keeps it
# under ExpeditionContext and says so in the top-level ActiveContext ("Main" / "Season"). Measured on the
# developer's saves 2026-10-20: a save carries exactly one of the two, so assuming BaseContext would present
# an Expedition save as having nothing to edit - and, worse, write an edit into a context the game ignores.
CONTEXTS = {"Main": "BaseContext", "Season": "ExpeditionContext"}
OPS = ("set_amount", "add", "remove")
SUBSTANCE, PRODUCT, TECHNOLOGY = "Substance", "Product", "Technology"
CARGO_KINDS = frozenset({SUBSTANCE, PRODUCT, TECHNOLOGY})
TECH_KINDS = frozenset({TECHNOLOGY})
CHESTS = 10


@dataclass(frozen=True)
class SaveKeys:
    """Readable key name -> the save's obfuscated key, from `mapping.json`.

    One way only, and strict: a name the mapping does not know, or one it maps from two different obfuscated
    keys, raises. Guessing at where a value lives is how an editor corrupts a save quietly.
    """
    by_name: Mapping[str, tuple[str, ...]]

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, str]) -> SaveKeys:
        """Invert `{obfuscated: readable}` (what `saves.load_mapping` returns)."""
        out: dict[str, tuple[str, ...]] = {}
        for obfuscated, readable in mapping.items():
            out[readable] = (*out.get(readable, ()), obfuscated)
        return cls(by_name=out)

    def find(self, readable: str) -> str | None:
        """The obfuscated key for `readable`, or None when this mapping does not have it.

        Used while *reading* the save - enumerating containers is best-effort, because a mapping from an
        older game version simply does not know a container the game has since added, and the right answer
        is to not offer it. Ambiguity still raises: two keys for one name means the editor cannot know which
        field it would be writing.
        """
        found = self.by_name.get(readable, ())
        if len(found) > 1:
            raise KeyError(f"{readable!r} is ambiguous: the mapping has {len(found)} keys for it ({', '.join(found)})")
        return found[0] if found else None

    def key(self, readable: str) -> str:
        """The one obfuscated key for `readable`, strictly. Used wherever the editor *writes*."""
        found = self.find(readable)
        if found is None:
            raise KeyError(f"the save mapping does not know a key called {readable!r}")
        return found


@dataclass(frozen=True)
class ItemFacts:
    """What the editor needs to know about one item: read from the installed game, never from the save."""
    item_id: str
    kind: str                   # Substance, Product or Technology
    max_amount: int             # the stack cap the game gives it


@dataclass(frozen=True)
class Change:
    """One staged change. `slot` is the game's (x, y) index; `item_id` and `amount` depend on the op."""
    container: str
    slot: tuple[int, int]
    op: str
    item_id: str | None = None
    amount: int | None = None


@dataclass(frozen=True)
class Container:
    """One place in the save that holds slots: its id for a form, its label for a person, where it lives."""
    id: str
    label: str
    path: tuple[Any, ...]       # readable key names, with ints for list positions
    accepts: frozenset[str]


# Every container the editor can reach, as (id, label, path inside PlayerStateData, what it accepts). Ships
# are expanded per owned ship; the paths are readable names, resolved through SaveKeys at the point of use.
FIXED_CONTAINERS: tuple[tuple[str, str, tuple[str, ...], frozenset[str]], ...] = (
    ("exosuit", "Exosuit", ("Inventory",), CARGO_KINDS),
    ("exosuit_cargo", "Exosuit cargo", ("Inventory_Cargo",), CARGO_KINDS),
    ("exosuit_tech", "Exosuit technology", ("Inventory_TechOnly",), TECH_KINDS),
    ("multitool", "Multi-tool", ("WeaponInventory",), CARGO_KINDS),
    ("freighter", "Freighter", ("FreighterInventory",), CARGO_KINDS),
    ("freighter_cargo", "Freighter cargo", ("FreighterInventory_Cargo",), CARGO_KINDS),
    ("freighter_tech", "Freighter technology", ("FreighterInventory_TechOnly",), TECH_KINDS),
    ("corvette", "Corvette storage", ("CorvetteStorageInventory",), CARGO_KINDS),
    ("cooking", "Cooking ingredients", ("CookingIngredientsInventory",), CARGO_KINDS),
    ("bait", "Bait box", ("FishBaitBoxInventory",), CARGO_KINDS),
)


def _at(tree: Mapping, keys: SaveKeys, path: tuple[Any, ...]) -> Any:
    """Follow `path` (readable names and list positions) through the obfuscated tree, or None."""
    node: Any = tree
    for step in path:
        if isinstance(step, int):
            if not isinstance(node, list) or step >= len(node):
                return None
            node = node[step]
            continue
        if not isinstance(node, dict):
            return None
        obfuscated = keys.find(step)
        if obfuscated is None:
            return None
        node = node.get(obfuscated)
    return node


def player_path(tree: Mapping, keys: SaveKeys) -> tuple[str, str] | None:
    """(context key, "PlayerStateData") for this save, or None when neither context holds a player state.

    The save's own ActiveContext is tried first; if it names a context this save does not actually carry,
    the other one is tried, because the file is what counts, not what it claims.
    """
    active = tree.get(keys.find("ActiveContext") or "")
    wanted = CONTEXTS.get(active) if isinstance(active, str) else None
    order = [wanted, *[c for c in CONTEXTS.values() if c != wanted]]
    for context in order:
        if context is None:
            continue
        if isinstance(_at(tree, keys, (context, "PlayerStateData")), dict):
            return (context, "PlayerStateData")
    return None


def _inventory_at(tree: Mapping, keys: SaveKeys, path: tuple[Any, ...]) -> dict | None:
    """The inventory at `path`, relative to this save's player state, or None when it has nothing there."""
    player = player_path(tree, keys)
    if player is None:
        return None
    node = _at(tree, keys, (*player, *path))
    if not isinstance(node, dict):
        return None
    slots_key = keys.find("Slots")
    if slots_key is None or not isinstance(node.get(slots_key), list):
        return None
    return node


def _ship_containers(tree: Mapping, keys: SaveKeys) -> list[Container]:
    """One container per owned ship, plus its technology, in the order the save lists them."""
    player = player_path(tree, keys)
    ships = _at(tree, keys, (*player, "ShipOwnership")) if player else None
    out: list[Container] = []
    for index in range(len(ships) if isinstance(ships, list) else 0):
        for suffix, label, key, accepts in (("", "Ship {}", "Inventory", CARGO_KINDS),
                                            ("_tech", "Ship {} technology", "Inventory_TechOnly", TECH_KINDS)):
            path = ("ShipOwnership", index, key)
            if _inventory_at(tree, keys, path) is not None:
                out.append(Container(f"ship:{index}{suffix}", label.format(index + 1), path, accepts))
    return out


def _chest_containers(tree: Mapping, keys: SaveKeys) -> list[Container]:
    """The ten storage containers the game numbers 1-10 on its own screens."""
    out = []
    for n in range(1, CHESTS + 1):
        path = (f"Chest{n}Inventory",)
        if _inventory_at(tree, keys, path) is not None:
            out.append(Container(f"chest:{n}", f"Storage container {n}", path, CARGO_KINDS))
    return out


def containers(tree: Mapping, keys: SaveKeys) -> list[Container]:
    """Every container *this* save has. A change against anything else could only ever fail."""
    out = [Container(cid, label, path, accepts)
           for cid, label, path, accepts in FIXED_CONTAINERS
           if _inventory_at(tree, keys, path) is not None]
    return out + _ship_containers(tree, keys) + _chest_containers(tree, keys)


def container_by_id(tree: Mapping, keys: SaveKeys, container_id: str) -> Container | None:
    """The container with this id, or None when the save does not have it."""
    return next((c for c in containers(tree, keys) if c.id == container_id), None)


def _index_of(slot: Mapping, keys: SaveKeys) -> tuple[int, int] | None:
    """A slot's (x, y), or None when it has no index (an empty husk the game left behind)."""
    index = slot.get(keys.key("Index"))
    if not isinstance(index, dict):
        return None
    return index.get(keys.key("X")), index.get(keys.key("Y"))


def _owned(inv: Mapping, keys: SaveKeys) -> set[tuple[int, int]]:
    """The slots the player has actually bought, from the inventory's own list."""
    valid = inv.get(keys.key("ValidSlotIndices"))
    out = set()
    for entry in valid if isinstance(valid, list) else []:
        if isinstance(entry, dict):
            out.add((entry.get(keys.key("X")), entry.get(keys.key("Y"))))
    return out


def _slot_at(inv: Mapping, keys: SaveKeys, want: tuple[int, int]) -> dict | None:
    """The filled slot at `want`, or None."""
    slots = inv.get(keys.key("Slots"))
    for entry in slots if isinstance(slots, list) else []:
        if isinstance(entry, dict) and entry.get(keys.key("Id")) and _index_of(entry, keys) == want:
            return entry
    return None


def _cap(slot: Mapping | None, facts: ItemFacts | None, keys: SaveKeys) -> int:
    """The largest amount this slot may hold: what the save says, else what the game says about the item."""
    if slot is not None:
        stored = slot.get(keys.key("MaxAmount"))
        if isinstance(stored, int) and stored > 0:
            return stored
    return facts.max_amount if facts else 1


def _problem_with_amount(amount: Any, cap: int) -> str | None:
    """Why `amount` is not a usable stack size."""
    if not isinstance(amount, int) or isinstance(amount, bool):
        return "The amount must be a whole number."
    if not 1 <= amount <= cap:
        return f"The amount must be between 1 and {cap}."
    return None


def _problem_with_add(change: Change, container: Container, slot: dict | None,
                      catalogue: Mapping[str, ItemFacts]) -> str | None:
    """Why this item cannot be put in this slot."""
    if slot is not None:
        return "That slot already holds something; remove it first or change its amount."
    facts = catalogue.get(str(change.item_id))
    if facts is None:
        return f"{change.item_id!r} is not an item this game installation knows."
    if facts.kind not in container.accepts:
        kinds = " or ".join(sorted(container.accepts)).lower()
        return f"{container.label} only takes {kinds}, and that is a {facts.kind.lower()}."
    return _problem_with_amount(change.amount, facts.max_amount)


def validate(change: Change, tree: Mapping, keys: SaveKeys,
             catalogue: Mapping[str, ItemFacts]) -> str | None:
    """Why `change` is refused, as a sentence for the person who made it, or None when it is sound."""
    if change.op not in OPS:
        return f"{change.op!r} is not something the editor can do to a slot."
    container = container_by_id(tree, keys, change.container)
    if container is None:
        return f"This save has no container called {change.container!r}."
    inv = _inventory_at(tree, keys, container.path)
    if tuple(change.slot) not in _owned(inv, keys):
        return f"{container.label} does not own slot {change.slot[0] + 1},{change.slot[1] + 1} in this save."
    slot = _slot_at(inv, keys, tuple(change.slot))
    if change.op == "add":
        return _problem_with_add(change, container, slot, catalogue)
    if slot is None:
        return f"{container.label} slot {change.slot[0] + 1},{change.slot[1] + 1} is empty."
    if change.op == "remove":
        return None
    return _problem_with_amount(change.amount, _cap(slot, catalogue.get(str(slot.get(keys.key("Id")))), keys))


def _item_label(item_id: Any) -> str:
    """'^CARBON' -> 'CARBON', the way `summary.item_name` does it (display names live in game data)."""
    text = str(item_id)
    return text[1:] if text.startswith("^") else text


def _describe(change: Change, container: Container, slot: Mapping | None, keys: SaveKeys) -> str:
    """The line the user reads in the pending list, before anything is written."""
    where = f"{container.label} slot {change.slot[0] + 1},{change.slot[1] + 1}"
    if change.op == "add":
        return f"{where}: + {_item_label(change.item_id)} x{change.amount}"
    name = _item_label(slot.get(keys.key("Id")) if slot else "")
    if change.op == "remove":
        return f"{where}: - {name}"
    return f"{where}: {name} {slot.get(keys.key('Amount')) if slot else '?'} -> {change.amount}"


def _new_slot(change: Change, facts: ItemFacts, keys: SaveKeys) -> dict:
    """A whole slot as the game writes one: the editor fills every field, not just the id."""
    return {keys.key("Type"): {keys.key("InventoryType"): facts.kind},
            keys.key("Id"): change.item_id,
            keys.key("Amount"): change.amount,
            keys.key("MaxAmount"): facts.max_amount,
            keys.key("Index"): {keys.key("X"): change.slot[0], keys.key("Y"): change.slot[1]}}


def _apply_one(tree: dict, change: Change, keys: SaveKeys, catalogue: Mapping[str, ItemFacts]) -> str:
    """Apply one already-validated change in place on `tree` (a copy) and return its description."""
    container = container_by_id(tree, keys, change.container)
    inv = _inventory_at(tree, keys, container.path)
    slots = inv[keys.key("Slots")]
    slot = _slot_at(inv, keys, tuple(change.slot))
    line = _describe(change, container, slot, keys)
    if change.op == "add":
        slots.append(_new_slot(change, catalogue[str(change.item_id)], keys))
    elif change.op == "remove":
        slots.remove(slot)
    else:
        # Only the amount is touched: a technology slot's damage and install state are the game's, not ours.
        slot[keys.key("Amount")] = change.amount
    return line


def apply(tree: Mapping, changes: list[Change], keys: SaveKeys,
          catalogue: Mapping[str, ItemFacts]) -> tuple[dict, list[str]]:
    """(the new tree, one description per change). Pure: the tree given is never touched.

    Every change is re-validated against the tree as it is at that point, so a pending change that has gone
    stale raises here rather than reaching the file. Changes apply in order, so the last word wins - the
    pending list the user reviewed is what they get.
    """
    out = copy.deepcopy(dict(tree))
    report = []
    for change in changes:
        problem = validate(change, out, keys, catalogue)
        if problem is not None:
            raise ValueError(problem)
        report.append(_apply_one(out, change, keys, catalogue))
    return out, report
