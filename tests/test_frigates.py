"""Tests for the frigate table: trait names from the game's trait table, frigates from the save, the view."""

import struct

from nms_connector import frigates, mbin

MARK = mbin.MARK


def trait_table(traits, record=frigates.TRAIT_RECORD) -> bytes:
    """frigatetraittable.mbin: a root list of GcFrigateTraitData records [(id, name key, stat, strength)]."""
    root, start = 0x10, 0x20
    data = bytearray(start + record * len(traits))      # no padding: the record size is derived from the length
    struct.pack_into("<QI4s", data, root, start - root, len(traits), MARK)
    for k, (tid, name, stat, strength) in enumerate(traits):
        p = start + k * record
        data[p:p + len(name)] = name.encode()
        data[p + 0x20:p + 0x20 + len(tid)] = tid.encode()
        struct.pack_into("<2I", data, p + 0x5C, frigates.STATS.index(stat), frigates.STRENGTHS.index(strength))
    return bytes(data)


TRAITS = [("COMBAT_PRI", "FLEET_TRAIT_PRI_COMBAT_1", "Combat", "Primary"),
          ("TRADING_BAD_4", "FLEET_TRAIT_NEG_TRADING_4", "Diplomatic", "NegativeSmall"),
          ("NORMANDY_1", "UI_NORMANDY_TRAIT1", "Combat", "Primary")]


def test_traits_are_read_from_the_games_table_and_checked():
    """Names, stat and strength per trait id (the Normandy's keys start with UI_, seen in build 25625620); a
    table with another record size is refused, so ids are shown instead of wrong names."""
    traits = frigates.parse_traits(trait_table(TRAITS))
    assert traits["COMBAT_PRI"] == {"name": "FLEET_TRAIT_PRI_COMBAT_1", "stat": "Combat", "strength": "Primary"}
    assert traits["TRADING_BAD_4"]["strength"] == "NegativeSmall" and "NORMANDY_1" in traits
    assert frigates.parse_traits(trait_table(TRAITS, record=0x70)) == {}
    assert frigates.load_traits(None)["traits"] == {}


def save():
    return {"BaseContext": {"PlayerStateData": {
        "FleetFrigates": [
            {"CustomName": "", "FrigateClass": {"FrigateClass": "Combat"}, "Race": {"AlienRace": "Traders"},
             "InventoryClass": {"InventoryClass": "B"}, "Stats": [24, 7, 5, 1, 12, 6, 0, 0, 0, 0, 0],
             "TraitIDs": ["^COMBAT_PRI", "^TRADING_BAD_4", "^"], "TotalNumberOfExpeditions": 29,
             "TotalNumberOfSuccessfulEvents": 111, "TotalNumberOfFailedEvents": 10, "DamageTaken": 0,
             "HomeSystemSeed": [True, "0xB70002925E80"]},
            {"CustomName": "Gamorra", "FrigateClass": {"FrigateClass": "Exploration"}, "Race": {"AlienRace": "Explorers"},
             "InventoryClass": {"InventoryClass": "C"}, "Stats": [3, 30, 4, 8], "TraitIDs": [], "DamageTaken": 3,
             "HomeSystemSeed": [True, "0x66E1FE4C2E21D0E6"]}],
        "FleetExpeditions": [{"AllFrigateIndices": [0]}]}}}


def test_frigates_are_read_with_their_record_and_whether_they_are_out():
    """Empty trait slots ("^") are dropped; a frigate listed by an expedition is out; DamageTaken means it needs a
    repair; the home system is the packed address of where it was bought."""
    combat, gamorra = frigates.frigates_from_save(save())
    assert combat["traits"] == ["COMBAT_PRI", "TRADING_BAD_4"] and combat["on_expedition"] and not combat["damaged"]
    assert combat["stats"]["Combat"] == 24 and combat["home"] == 0xB70002925E80 and combat["grade"] == "B"
    assert gamorra["damaged"] and not gamorra["on_expedition"] and frigates.frigate_label(gamorra) == "Gamorra"
    assert frigates.frigate_label(combat) == "Combat frigate"


class Gamedata:
    def icon_name(self, icon_id):
        return icon_id.lower() + ".png"


class Texts:
    gamedata = Gamedata()

    def key(self, key, sibling=None):
        return {"FLEET_TRAIT_PRI_COMBAT_1": "Combat Specialist", "FLEET_TRAIT_NEG_TRADING_4": "Thief On Board"}.get(key, key)


def test_the_frigate_table_shows_class_icons_traits_record_home_and_state():
    """Class icon on the frigate, the primary trait's icon on the traits; traits named by the game (negative
    ones marked); success rate of the events; an unknown home system stays empty."""
    traits = frigates.parse_traits(trait_table(TRAITS))
    rows = frigates.frigate_sections(frigates.frigates_from_save(save()), traits, Texts(),
                                     lambda key: "Kayana XIV" if key == 0xB70002925E80 else None)[0]["rows"]
    combat, gamorra = rows
    assert combat[0]["icon"] == "frigate_class_combat.png" and "Thief On Board (negative)" in combat[0]["hint"]
    assert combat[8] == {"text": "Combat Specialist (primary), Thief On Board (negative)",
                         "icon": "frigate_trait_primary_combat.png"}
    assert combat[9] == "29 expeditions, 92 % of events won" and combat[10] == "Kayana XIV" and combat[11] == "on an expedition"
    assert gamorra[10] is None and gamorra[11] == "damaged - repair it" and gamorra[8] is None
    assert frigates.frigate_sections([], traits, Texts(), lambda k: None)[0]["text"] == "No frigates in this save."
    assert len(frigates.icon_textures()) == 25
