"""Bases, item values and the "where am I" sentence (asked for on 2026-10-07).

The save keeps every base with the parts it is built from; the plugin names them from the item database, says
which planet a base stands on, and gives the persona a sentence for the player's position instead of a label.
"""
import pytest

from nms_connector import planets_view, summary
from test_connector import FakeCtx, create_plugin


def base_save(objects, address=4611351810039424, kind="HomePlanetBase", name="Home", updated=1757075039):
    """A save holding one base, as summary.summarize reads it."""
    return {"BaseContext": {"PlayerStateData": {"UniverseAddress": {"GalacticAddress": {}},
                                "PersistentPlayerBases": [
                                    {"Name": name, "GalacticAddress": address,
                                     "BaseType": {"PersistentBaseTypes": kind}, "Objects": objects,
                                     "LastUpdateTimestamp": updated,
                                     "Owner": {"USN": "ReatKay"}}]}}}


def test_a_base_carries_its_parts_planet_and_build_time():
    """Every part of a base is counted by its ObjectID (the item id without the caret, so the item database
    names it), with the planet index from the address and when it was last built on - the view had only a
    part count before, so "what is in my base?" could not be answered."""
    snap = summary.summarize(base_save([{"ObjectID": "^W_WALL"}, {"ObjectID": "^W_WALL"},
                                        {"ObjectID": "^BASE_FLAG"}, {"ObjectID": ""}, 7]))
    base = snap["bases"][0]
    assert base["parts"] == {"W_WALL": 2, "BASE_FLAG": 1}       # blank ids and non-objects are skipped
    assert base["objects"] == 5 and base["last_update"] == 1757075039
    assert base["type"] == "Planet base" and base["planet_index"] is not None


def test_base_types_the_save_uses_are_named():
    """A ship interior and a freighter base are bases too; an unknown type keeps the game's own word rather
    than being dropped (read from a real save: HomePlanetBase, FreighterBase and PlayerShipBase all occur)."""
    for kind, shown in [("PlayerShipBase", "Ship interior"), ("FreighterBase", "Freighter base"),
                        ("HomePlanetBase", "Planet base"), ("SomethingNew", "SomethingNew")]:
        snap = summary.summarize(base_save([], kind=kind))
        assert snap["bases"][0]["type"] == shown


def test_the_bases_table_names_the_parts_and_the_planet(tmp_path, monkeypatch):
    """The Bases table says where each base stands, what it is built from (the tooltip lists every part) and
    when it was last built on, newest first; the parts cell sorts by how many parts a base has."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    page, ctx = plugin.page, plugin.context()
    snap = {"bases": [
        {"name": "Small", "type": "Planet base", "system": None, "galaxy": "Euclid", "portal": "0001",
         "objects": 3, "planet_index": 0, "parts": {"W_WALL": 3}, "last_update": 1757075039},
        {"name": "Big", "type": "Planet base", "system": None, "galaxy": "Euclid", "portal": "0002",
         "objects": 9, "planet_index": 0, "parts": {"W_WALL": 5, "BASE_FLAG": 4}, "last_update": 1791328862},
    ]}
    table = page.bases_table(snap, ctx)
    assert table["columns"] == ["Name", "Type", "Where", "Galaxy", "Parts", "What is in it", "Last built on"]
    assert [r[0] for r in table["rows"]] == ["Big", "Small"]            # newest first
    cell = table["rows"][0][5]
    # Sorted by how many kinds of part a base has: the total is already the Parts column beside it.
    assert cell["sort"] == 2 and cell["text"].startswith("5x ") and "Built from:" in cell["hint"]
    assert table["rows"][0][6] and table["rows"][0][6] != "-"           # a readable date


def test_item_rows_carry_the_value_of_the_stack_and_of_one_unit(tmp_path, monkeypatch):
    """Like the game's own tooltip ("Insgesamt 6.426 Units" above "Je 6 Units"): what the whole stack is worth
    and what one unit is worth. Both stay numbers so the column sorts by size, and an item without a base
    value leaves them empty instead of claiming 0."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    page, ctx = plugin.page, plugin.context()
    monkeypatch.setattr(type(plugin.gamedata), "lookup",
                        lambda self, i: {"TRITIUM": {"en": "Tritium", "value": 6}, "FREE": {"en": "Free"}}.get(i))
    assert "Value (stack)" in page.item_columns() and "Value (each)" in page.item_columns()
    rows = page.item_rows([["TRITIUM", 1071, 9999], ["FREE", 5, 10]], ctx)
    assert rows[0][-2:] == [6426, 6]        # 1,071 x 6 units, exactly what the game shows
    assert rows[1][-2:] == [None, None]


def test_where_am_i_is_a_full_sentence_naming_the_planet(tmp_path, monkeypatch):
    """The persona used to receive a label ("You are in the system X"), so "where am I?" was answered with one.
    It now gets the sentence to say, with the planet - or "in space", or an honest "cannot be read right now"."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    ctx = plugin.context()
    key = 0x79

    def planet(text, where="planet"):
        monkeypatch.setattr(planets_view, "current_planet",
                            lambda c, k: {"text": text, "where": where, "exact": True})

    planet("Corrodia (Yaksh Primus)")
    said = planets_view.where_sentence(ctx, key, "Euclid", "006202925E80")
    assert said.startswith("You are currently on the planet Corrodia (Yaksh Primus) in the system ")
    assert "(Euclid galaxy, portal address 006202925E80)" in said

    planet("in space", where="space")
    assert planets_view.where_sentence(ctx, key, "Euclid").startswith("You are currently in space in the system ")

    planet("unknown (...)", where="unknown")
    unsure = planets_view.where_sentence(ctx, key, "Euclid")
    assert "cannot be read right now" in unsure and "You are currently in the system" in unsure

    # Without live data the save only says which system - it must not claim a planet.
    offline = planets_view.where_sentence(ctx, key, "Euclid", live=False)
    assert offline.startswith("At the last save you were in the system ") and "planet" not in offline
    assert planets_view.where_sentence(ctx, None, "Euclid") is None


def test_the_answer_rule_travels_apart_from_the_data(tmp_path, monkeypatch):
    """How to answer ("answer a 'where am I' question with this sentence") goes in `instructions`, not in the
    data text: the app's data block tells the model that everything inside it is data and never instructions,
    so a rule written into the text would contradict the block it sits in. The sentence itself stays in the
    data, where the facts belong."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.snapshot = {"location": {"galaxy": "Euclid", "portal": "0001"}, "bases": [], "units": 0, "nanites": 0,
                       "quicksilver": 0, "freighter": {"name": None}, "ships": [], "storage": [],
                       "exosuit": [], "current_mission": None, "saved_at": None}
    monkeypatch.setattr(type(plugin), "here", lambda self: 0x79)
    monkeypatch.setattr(planets_view, "where_sentence", lambda *a, **k: "You are currently in space in X.")
    block = plugin.companion.chat_context("where am I?")
    # After the conversation rules every data reply carries (companion.CONVERSATION_RULES), the position rule.
    assert block["instructions"][-1:] == [
        "Asked where they are, answer with this sentence, translated into the player's language and nothing in "
        'front of it: "You are currently in space in X."']
    assert "You are currently in space in X." in block["text"]      # the fact stays data
    assert "answer with this sentence" not in block["text"]         # the rule does not


def test_the_persona_is_given_the_sentence_and_the_bases(tmp_path, monkeypatch):
    """The chat block carries the position sentence and, for a question about bases, where each one is and
    what it is built from; a question about something else leaves the base lines out."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.snapshot = {"bases": [{"name": "Kay City Outpost", "type": "Planet base", "system": None,
                                  "galaxy": "Euclid", "portal": "0001", "objects": 4, "planet_index": 0,
                                  "parts": {"W_WALL": 4}, "last_update": 1757075039}]}
    ctx = plugin.context()
    lines = plugin.companion.base_lines({"bases"}, ctx)
    assert lines[0].startswith("Bases (1)") and "Kay City Outpost (Planet base)" in lines[1]
    assert "4 parts" in lines[1] and "last built on" in lines[1]
    assert any("built from:" in line for line in lines)
    assert plugin.companion.base_lines({"copper"}, ctx) == []
    # Naming a base asks about it too, without the word "base".
    assert plugin.companion.base_lines({"outpost"}, ctx)


@pytest.mark.parametrize("prompt_part", [
    "in full sentences", "You are currently on the planet", "You are currently in space",
])
def test_the_prompt_asks_for_whole_sentences(prompt_part):
    """The persona is told to answer in sentences and is shown the shape of a position answer; without that it
    replied with bare labels."""
    from nms_connector import companion
    assert prompt_part in companion.PERSONA_PROMPT
