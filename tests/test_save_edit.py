"""The savegame editor's edit core: the containers it can reach, what it refuses, and what `apply` produces.

Everything here is pure - a tree in, a tree out - so the rules are tested without a save file, a game or a
host. The commit pipeline that takes these changes to disk is tested in `tests/test_save_commit.py`.
"""

from __future__ import annotations

import copy

import pytest

from nms_connector.save_edit import (Change, ItemFacts, SaveKeys, apply, containers, validate)

# The obfuscated names this fixture uses. The real mapping.json gives one obfuscated key per readable name
# (verified 2026-10-20: no readable name is shared), which is what makes the one-way lookup safe.
MAPPING = {
    "BC1": "BaseContext", "PSD": "PlayerStateData",
    "INV": "Inventory", "ICA": "Inventory_Cargo", "ITO": "Inventory_TechOnly",
    "SHO": "ShipOwnership", "WPI": "WeaponInventory", "FRI": "FreighterInventory",
    "CH1": "Chest1Inventory", "CH2": "Chest2Inventory",
    "SLT": "Slots", "VSI": "ValidSlotIndices", "IDX": "Index", "XX1": "X", "YY1": "Y",
    "ID1": "Id", "AM1": "Amount", "MX1": "MaxAmount", "TY1": "Type", "IT1": "InventoryType",
    "DMG": "DamageFactor", "FIN": "FullyInstalled", "NM1": "Name",
}

KEYS = SaveKeys.from_mapping(MAPPING)

CATALOGUE = {
    "^CARBON": ItemFacts("^CARBON", "Substance", 9999),
    "^AMMO": ItemFacts("^AMMO", "Product", 9999),
    "^LASER": ItemFacts("^LASER", "Technology", 1),
    "^HYPERDRIVE": ItemFacts("^HYPERDRIVE", "Technology", 1),
}


def slot(x, y, item=None, kind="Substance", amount=0, extra=None):
    """One raw slot, obfuscated, as the game writes it."""
    if item is None:
        return {}
    out = {"TY1": {"IT1": kind}, "ID1": item, "AM1": amount, "MX1": 9999, "IDX": {"XX1": x, "YY1": y}}
    out.update(extra or {})
    return out


def inventory(slots, width=4, height=2):
    """An inventory whose owned slots are the full width x height grid."""
    return {"SLT": slots,
            "VSI": [{"XX1": x, "YY1": y} for y in range(height) for x in range(width)]}


def tree():
    """A save tree with an exosuit (two filled slots), a tech-only container, a ship and one storage box."""
    return {"BC1": {"PSD": {
        "INV": inventory([slot(0, 0, "^CARBON", "Substance", 120), slot(1, 0, "^AMMO", "Product", 50)]),
        "ITO": inventory([slot(0, 0, "^LASER", "Technology", 1, {"DMG": 0.0, "FIN": True})], width=2, height=1),
        "SHO": [{"INV": inventory([slot(0, 0, "^CARBON", "Substance", 7)])}],
        "CH1": inventory([], width=2, height=1),
        "WPI": inventory([slot(0, 0, "^LASER", "Technology", 1)], width=2, height=1),
    }}}


def test_containers_lists_only_what_this_save_has():
    """The picker must offer the containers that exist in *this* save - a save with no freighter must not
    offer a freighter - because a change against a missing container could only ever fail."""
    found = {c.id for c in containers(tree(), KEYS)}

    assert "exosuit" in found
    assert "exosuit_tech" in found
    assert "ship:0" in found
    assert "chest:1" in found
    assert "freighter" not in found
    assert "chest:2" not in found


def test_containers_label_names_the_container_for_a_human():
    """The label is what the Editor tab shows; it must read as the game names things, not as a save key."""
    labels = {c.id: c.label for c in containers(tree(), KEYS)}

    assert labels["exosuit"] == "Exosuit"
    assert labels["exosuit_tech"] == "Exosuit technology"
    assert labels["chest:1"] == "Storage container 1"


def test_set_amount_changes_only_that_slots_amount():
    """The core edit. Everything else in the tree - the other slots, the other containers - must come back
    untouched, because a save holds far more than the editor understands."""
    before = tree()
    change = Change(container="exosuit", slot=(0, 0), op="set_amount", amount=9999)

    after, report = apply(before, [change], KEYS, CATALOGUE)

    slots = after["BC1"]["PSD"]["INV"]["SLT"]
    assert slots[0]["AM1"] == 9999
    assert slots[1] == before["BC1"]["PSD"]["INV"]["SLT"][1]
    assert report == ["Exosuit slot 1,1: CARBON 120 -> 9999"]


def test_apply_does_not_touch_the_tree_it_was_given():
    """`apply` is pure: the commit pipeline validates, applies and only then writes, and a failure anywhere
    must leave the original tree usable. An in-place edit would make a half-applied save possible."""
    before = tree()
    snapshot = copy.deepcopy(before)

    apply(before, [Change("exosuit", (0, 0), "set_amount", amount=1)], KEYS, CATALOGUE)

    assert before == snapshot


def test_add_fills_an_empty_owned_slot():
    """Adding an item writes a whole slot - type, id, amount, cap and its index - because the game expects
    every field, not just the id."""
    change = Change("chest:1", (1, 0), "add", item_id="^CARBON", amount=500)

    after, report = apply(tree(), [change], KEYS, CATALOGUE)

    added = after["BC1"]["PSD"]["CH1"]["SLT"][0]
    assert added["ID1"] == "^CARBON"
    assert added["AM1"] == 500
    assert added["TY1"]["IT1"] == "Substance"
    assert added["IDX"] == {"XX1": 1, "YY1": 0}
    assert report == ["Storage container 1 slot 2,1: + CARBON x500"]


def test_remove_drops_the_slot_entirely():
    """Removing must take the slot out of the list rather than leave an empty husk: the game reads the list,
    and a slot with an id of None is not something it writes itself."""
    after, report = apply(tree(), [Change("exosuit", (0, 0), "remove")], KEYS, CATALOGUE)

    ids = [s.get("ID1") for s in after["BC1"]["PSD"]["INV"]["SLT"]]
    assert ids == ["^AMMO"]
    assert report == ["Exosuit slot 1,1: - CARBON"]


def test_editing_technology_keeps_the_fields_the_editor_does_not_own():
    """A technology slot carries damage and install state the editor has no business changing. Those must
    survive an amount edit untouched - this is the risk the user accepted when tech was put in scope."""
    after, _ = apply(tree(), [Change("exosuit_tech", (0, 0), "set_amount", amount=1)], KEYS, CATALOGUE)

    tech = after["BC1"]["PSD"]["ITO"]["SLT"][0]
    assert tech["DMG"] == 0.0
    assert tech["FIN"] is True


def test_changes_apply_in_order():
    """A changeset is applied as one unit; two changes to the same slot must end with the later one, so the
    pending list the user reviews is what they get."""
    changes = [Change("exosuit", (0, 0), "set_amount", amount=5),
               Change("exosuit", (0, 0), "set_amount", amount=77)]

    after, report = apply(tree(), changes, KEYS, CATALOGUE)

    assert after["BC1"]["PSD"]["INV"]["SLT"][0]["AM1"] == 77
    assert len(report) == 2


@pytest.mark.parametrize("change, reason", [
    pytest.param(Change("freighter", (0, 0), "set_amount", amount=1), "container", id="missing-container"),
    pytest.param(Change("exosuit", (9, 9), "set_amount", amount=1), "own", id="slot-not-owned"),
    pytest.param(Change("exosuit", (3, 1), "set_amount", amount=1), "empty", id="set-amount-on-empty-slot"),
    pytest.param(Change("exosuit", (3, 1), "remove"), "empty", id="remove-empty-slot"),
    pytest.param(Change("exosuit", (0, 0), "add", item_id="^CARBON", amount=1), "already", id="add-to-filled-slot"),
    pytest.param(Change("chest:1", (1, 0), "add", item_id="^NOPE", amount=1), "not an item", id="unknown-item"),
    pytest.param(Change("exosuit", (0, 0), "set_amount", amount=0), "between", id="amount-zero"),
    pytest.param(Change("exosuit", (0, 0), "set_amount", amount=100000), "between", id="amount-over-cap"),
    pytest.param(Change("exosuit_tech", (1, 0), "add", item_id="^CARBON", amount=1), "technology", id="substance-into-tech"),
    pytest.param(Change("exosuit", (0, 0), "frobnicate"), "not something", id="unknown-op"),
])
def test_validate_refuses_and_says_why(change, reason):
    """Every refusal returns a sentence the user reads in the form, the way `PluginSettings.update` does. A
    change that cannot be explained cannot be fixed by the person who made it."""
    problem = validate(change, tree(), KEYS, CATALOGUE)

    assert problem is not None, "the change should have been refused"
    assert reason in problem, f"{problem!r} does not mention {reason!r}"


def test_validate_accepts_a_sound_change():
    """The happy path: a change the pipeline should let through returns None."""
    assert validate(Change("exosuit", (1, 0), "set_amount", amount=200), tree(), KEYS, CATALOGUE) is None


def test_apply_refuses_to_apply_an_invalid_change():
    """`apply` re-validates rather than trusting its caller: the commit pipeline validates against the tree
    as it is *now*, and a stale pending change must not slip past into a written save."""
    with pytest.raises(ValueError, match="own"):
        apply(tree(), [Change("exosuit", (9, 9), "set_amount", amount=1)], KEYS, CATALOGUE)


def test_save_keys_refuses_an_ambiguous_readable_name():
    """The one-way lookup is only safe while each readable name has a single obfuscated key. A future
    mapping.json that breaks that must fail loudly rather than silently edit the wrong field."""
    keys = SaveKeys.from_mapping({"AA1": "Units", "BB2": "Units"})

    with pytest.raises(KeyError, match="Units"):
        keys.key("Units")


def test_save_keys_refuses_a_name_the_mapping_does_not_know():
    """A key the mapping cannot translate means the editor would be guessing at where a value lives."""
    with pytest.raises(KeyError, match="Nonesuch"):
        KEYS.key("Nonesuch")


def expedition_tree():
    """An Expedition save: the player's state hangs off ExpeditionContext, not BaseContext.

    Real shape, from the developer's save3.hg on 2026-10-20: the top-level ActiveContext says "Season" and
    only ExpeditionContext carries PlayerStateData.
    """
    return {"XTp": "Season", "EXC": {"PSD": {
        "INV": inventory([slot(0, 0, "^CARBON", "Substance", 120)]),
    }}}


def test_containers_follows_active_context_into_an_expedition_save():
    """An Expedition save keeps the player's state under ExpeditionContext. Assuming BaseContext finds
    nothing at all, which would silently present an expedition save as having no containers to edit."""
    keys = SaveKeys.from_mapping({**MAPPING, "XTp": "ActiveContext", "EXC": "ExpeditionContext"})

    found = {c.id for c in containers(expedition_tree(), keys)}

    assert "exosuit" in found


def test_an_edit_in_an_expedition_save_lands_in_the_expedition_context():
    """And the edit must be written where that save actually keeps it, not into a BaseContext the save does
    not have - an edit that appears to succeed but changes nothing is the worst outcome of the two."""
    keys = SaveKeys.from_mapping({**MAPPING, "XTp": "ActiveContext", "EXC": "ExpeditionContext"})
    change = Change("exosuit", (0, 0), "set_amount", amount=999)

    after, _ = apply(expedition_tree(), [change], keys, CATALOGUE)

    assert after["EXC"]["PSD"]["INV"]["SLT"][0]["AM1"] == 999
