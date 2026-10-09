"""How often an item can be made from the holdings, and the portal address as glyph names (chat test 2026-10-09)."""

from nms_connector import craftable
from test_recipes import ITEMS, book


def label(item_id):
    """The display name used in these tests."""
    return (ITEMS.get(item_id) or {}).get("en") or item_id


def test_max_crafts_names_the_limiting_ingredient():
    """25 Chromatic Metal + 20 Condensed Carbon with 1,314 and 50: 2 times (50 // 20), limited by the carbon. A
    missing ingredient makes it 0; a recipe without ingredients cannot be counted (0, None)."""
    needs = [("STELLAR2", 25), ("FUEL2", 20)]
    assert craftable.max_crafts(needs, {"STELLAR2": 1314, "FUEL2": 50}) == (2, "FUEL2")
    assert craftable.max_crafts(needs, {"STELLAR2": 1314}) == (0, "FUEL2")
    assert craftable.max_crafts([], {}) == (0, None)


def test_option_line_says_how_often_what_limits_and_whether_it_is_enough():
    """The line carries the owned amount of every ingredient, the count, the limit and - for a wanted number - 'enough'
    or what is missing. Why: the model was left to do this sum and answered 'the data has no quantities'."""
    needs = [("STELLAR2", 25), ("FUEL2", 20)]
    have = {"STELLAR2": 1314, "FUEL2": 50}
    line = craftable.option_line(needs, have, label, None)
    assert line == ("25 Chromatic Metal (you have 1,314) + 20 Condensed Carbon (you have 50): can be done 2 times, "
                    "limited by Condensed Carbon")
    assert craftable.option_line(needs, have, label, 2).endswith("; enough for 2")
    assert craftable.option_line(needs, have, label, 3).endswith("; NOT enough for 3, missing 10 Condensed Carbon")
    refiner = craftable.option_line([("TOXIC1", 2)], {"TOXIC1": 9}, label, None, output=3)
    assert "can be done 4 times (12 items)" in refiner


def test_when_a_question_asks_for_a_craft_count():
    """'how many can I make', 'do I have enough ...' and the German forms ask; a plain recipe or amount question does
    not; a number is read from the message itself and not from the app's follow-up label."""
    ask = craftable.asks_craft_count
    assert ask({"how", "many", "can", "i", "make"}) and ask({"hab", "ich", "genug", "antimaterie"})
    assert ask({"wie", "viele", "kann", "ich", "herstellen"}) and ask({"do", "i", "have", "enough", "copper"})
    assert not ask({"recipe", "for", "ammonia"}) and not ask({"how", "much", "copper", "do", "i", "have"})
    assert craftable.requested_times("enough Antimatter for 3 Warp Cells?") == 3
    wrapped = "how many can i make?" + chr(10) * 2 + "(follow-up to the user's previous message: recipe for 25 things)"
    assert craftable.requested_times(wrapped) is None


def test_the_portal_address_becomes_glyph_names():
    """The digits 0-F are Sunset, Bird, Face, Diplo, Eclipse, Balloon, Boat, Bug, Dragonfly, Galaxy, Voxel, Fish,
    Tent, Rocket, Tree, Atlas: 106202925E80 is Bird, Sunset, Boat, Face ... Dragonfly, Sunset. Anything that is not
    hex gives no glyphs instead of a wrong reading."""
    assert craftable.glyph_names("106202925E80") == [
        "Bird", "Sunset", "Boat", "Face", "Sunset", "Face", "Galaxy", "Face", "Balloon", "Tree", "Dragonfly", "Sunset"]
    assert craftable.glyph_names("0F") == ["Sunset", "Atlas"] and craftable.glyph_names("ab") == ["Voxel", "Fish"]
    assert craftable.glyph_names("12G4") == [] and craftable.glyph_names(None) == []


def test_the_persona_computes_what_can_be_made_and_names_the_glyphs(tmp_path, monkeypatch):
    """The 'how many of those can I make?' follow-up of the chat (wrapped by the app) and 'enough for 3' get the
    computed lines for Antimatter; 'in glyphs' gets the glyph names; other questions get neither."""
    from test_connector import FakeCtx, create_plugin
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.tables.recipes = book()
    plugin.gamedata.items = dict(ITEMS)
    snap = {"exosuit": [["STELLAR2", 1314, 9999], ["FUEL2", 50, 9999]], "exosuit_cargo": [], "ships": [],
            "freighter": {"inventory": []}, "storage": [], "location": {"portal": "106202925E80"}}
    wrapped = "how many of those can I make?" + chr(10) * 2 + "(follow-up to the user's previous message: recipe for Antimatter)"
    words = {"how", "many", "of", "those", "can", "i", "make", "recipe", "for", "antimatter"}
    lines = plugin.companion.craft_lines(wrapped, words, snap)
    assert lines[0].startswith("What you can make of Antimatter") and "can be done 2 times" in lines[1]
    assert plugin.companion.craft_lines("recipe for antimatter", {"recipe", "for", "antimatter"}, snap) == []
    assert plugin.companion.craft_lines(wrapped, words, None) == []
    glyphs = plugin.companion.glyph_lines({"portal", "address", "in", "glyphen"}, snap)
    assert glyphs and "Bird (1), Sunset (0), Boat (6), Face (2)" in glyphs[0]
    assert plugin.companion.glyph_lines({"portal", "address"}, snap) == []


def test_the_wanted_number_belongs_to_the_item_after_it():
    """'Hab ich genug Antimaterie für 3 Warpzellen?' wants 3 Warp Cells, not 3 Antimatter: the 'enough for 3' check on
    the Antimatter's own recipe made the model answer 'yes, 3 can be made' in one run of three (live check)."""
    names = {"ANTIMATTER": ["Antimatter", "Antimaterie"], "WARPCELL": ["Warp Cell", "Warpzelle"]}
    assert craftable.target_item("Hab ich genug Antimaterie für 3 Warpzellen?", names) == "WARPCELL"
    assert craftable.target_item("enough Antimatter for 3 Warp Cells?", names) == "WARPCELL"
    assert craftable.target_item("do I have enough Antimatter?", names) is None             # no number
    assert craftable.target_item("3 Antimatter, how many can I make", names) == "ANTIMATTER"
    wrapped = "how many?" + chr(10) * 2 + "(follow-up to the user's previous message: 3 Antimatter)"
    assert craftable.target_item(wrapped, names) is None


def test_only_the_target_item_gets_the_enough_check(tmp_path, monkeypatch):
    """craft_lines adds '; enough for N' / 'NOT enough for N' only to the item the number belongs to."""
    from test_connector import FakeCtx, create_plugin
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.tables.recipes = book()
    plugin.gamedata.items = dict(ITEMS)
    snap = {"exosuit": [["STELLAR2", 1314, 9999], ["FUEL2", 50, 9999]], "exosuit_cargo": [], "ships": [],
            "freighter": {"inventory": []}, "storage": [], "location": {}}
    lines = plugin.companion.craft_lines("enough Chromatic Metal for 3 Antimatter?",
                                         {"enough", "chromatic", "metal", "for", "3", "antimatter"}, snap)
    text = "\n".join(lines)
    assert text.count("enough for 3") == 1 and "NOT enough for 3, missing 10 Condensed Carbon" in text   # one line, the Antimatter's
def test_a_needs_question_asks_for_the_craft_counts_too():
    """"what do I need", "which ingredients am I missing", "was brauche ich" ask; a plain amount question does not.

    Expected: asks_needs is true for the need/ingredient/missing words in five languages and false otherwise, while
    asks_craft_count keeps its own meaning. It matters because "Which ingredients for Antimatter am I missing?"
    produced a block with no item lines at all, and the persona answered that the data holds no ingredient
    quantities - with both ingredients in the save (chat test 2026-10-09)."""
    assert craftable.asks_needs({"what", "do", "i", "need", "for", "antimatter"})
    assert craftable.asks_needs({"which", "ingredients", "am", "i", "missing"})
    assert craftable.asks_needs({"was", "brauche", "ich", "für", "antimaterie"})
    assert craftable.asks_needs({"welche", "zutaten", "fehlen", "mir"})
    assert craftable.asks_needs({"qué", "ingredientes", "necesito"}) and craftable.asks_needs({"il", "manque", "quoi"})
    assert not craftable.asks_needs({"how", "much", "copper", "do", "i", "have"})
    assert not craftable.asks_craft_count({"what", "do", "i", "need", "for", "antimatter"})


def test_a_needs_question_spells_out_what_is_missing_for_one(tmp_path, monkeypatch):
    """"Which ingredients for Antimatter am I missing?" gets the ingredients, the holdings of each and what is
    short of one Antimatter.

    Expected: the lines name both ingredients with the owned amounts and end in "NOT enough for 1, missing ..."
    when one is short; with the holdings sufficient they say "enough for 1". Why: the counting is what the model
    cannot do reliably, and this is the phrasing a player uses most."""
    from test_connector import FakeCtx, create_plugin
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.tables.recipes = book()
    plugin.gamedata.items = dict(ITEMS)
    short = {"exosuit": [["STELLAR2", 1314, 9999], ["FUEL2", 5, 9999]], "exosuit_cargo": [], "ships": [],
             "freighter": {"inventory": []}, "storage": []}
    question = "Which ingredients for Antimatter am I missing?"
    words = {"which", "ingredients", "for", "antimatter", "am", "i", "missing"}
    lines = plugin.companion.craft_lines(question, words, short)
    assert lines[0].startswith("What you can make of Antimatter")
    assert "25 Chromatic Metal (you have 1,314)" in lines[1] and "20 Condensed Carbon (you have 5)" in lines[1]
    assert lines[1].endswith("NOT enough for 1, missing 15 Condensed Carbon")

    plenty = {**short, "exosuit": [["STELLAR2", 1314, 9999], ["FUEL2", 50, 9999]]}
    assert plugin.companion.craft_lines(question, words, plenty)[1].endswith("enough for 1")


def test_an_explicit_number_still_wins_over_the_implicit_one(tmp_path, monkeypatch):
    """"Do I need more for 3 Antimatter?" counts three, not one.

    Expected: the line is about 3. The implicit "one" of a needs question must not override a number the player
    actually gave."""
    from test_connector import FakeCtx, create_plugin
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.tables.recipes = book()
    plugin.gamedata.items = dict(ITEMS)
    snap = {"exosuit": [["STELLAR2", 1314, 9999], ["FUEL2", 50, 9999]], "exosuit_cargo": [], "ships": [],
            "freighter": {"inventory": []}, "storage": []}
    lines = plugin.companion.craft_lines("Do I need more for 3 Antimatter?",
                                         {"do", "i", "need", "more", "for", "3", "antimatter"}, snap)
    assert "NOT enough for 3, missing 10 Condensed Carbon" in lines[1]
