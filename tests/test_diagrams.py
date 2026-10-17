"""Recipes as structured data for the app's chat diagrams (diagrams.py, companion.recipe_diagrams): the model's own
wording could not be relied on (chat tests 2026-10-10/11), so chat_context hands the app the recipes as data."""

from nms_connector import diagrams, game_terms, recipes
from test_connector import FakeCtx, create_plugin
from test_recipes import ITEMS, book

ICONS = {"TOXIC1": "substance.biome.toxic.png", "PLANT_TOXIC": "substance.plant.toxic.png", "SALT": "substance.water.1.png",
         "GAS3": "gas.1.png"}


def test_every_recipe_that_makes_the_item_becomes_a_diagram():
    """Ammonia's two refiner recipes become two diagrams, best yield first (as the persona's lines): ingredients and
    result with amount, name and icon (an item without a converted icon has none - the card then shows no picture),
    and the refiner the game names."""
    out = diagrams.item_diagrams(book(), ITEMS.get, ICONS.get, ["TOXIC1"], recipes.ENGLISH, None)
    assert len(out) == 2
    assert out[0]["ingredients"] == [{"amount": 1, "name": "Nitrogen", "icon": "gas.1.png"},
                                     {"amount": 1, "name": "Di-hydrogen"}]
    assert out[0]["result"] == {"amount": 1, "name": "Ammonia", "icon": "substance.biome.toxic.png"}
    assert out[0]["station"].endswith("or larger")
    assert out[1]["ingredients"] == [{"amount": 2, "name": "Fungal Mould", "icon": "substance.plant.toxic.png"},
                                     {"amount": 1, "name": "Salt", "icon": "substance.water.1.png"}]


def test_cooking_and_crafting_recipes_become_diagrams_too():
    """A dish's Nutrient Processor recipes and an item's crafting recipe are drawn as well - the chat test that showed
    "1 Kuchenteig + 1 Anormale Marmelade + 1 Sahne [K2]" was a cooking question."""
    stew = diagrams.item_diagrams(book(), ITEMS.get, ICONS.get, ["FOOD_STEW"], recipes.ENGLISH, None)
    assert [i["name"] for i in stew[0]["ingredients"]] == ["Ammonia", "Meat", "Salt"] and stew[0]["result"]["name"] == "Toxic Stew"
    antimatter = diagrams.item_diagrams(book(), ITEMS.get, ICONS.get, ["ANTIMATTER"], recipes.ENGLISH, None)
    assert antimatter == [{"ingredients": [{"amount": 25, "name": "Chromatic Metal"}, {"amount": 20, "name": "Condensed Carbon"}],
                           "result": {"amount": 1, "name": "Antimatter"}}]


def test_names_follow_the_language_of_the_question():
    """A German question (an item named in German, or German words) gets German names; an English one English
    names; an English game always English."""
    assert diagrams.answer_language("Wie bekomme ich Ammoniak?", ["TOXIC1"], ITEMS.get, "german") == "german"
    assert diagrams.answer_language("Wie stelle ich den Ewigen Kuchen her?", [], ITEMS.get, "german") == "german"
    assert diagrams.answer_language("How do I make Ammonia?", ["TOXIC1"], ITEMS.get, "german") == recipes.ENGLISH
    assert diagrams.answer_language("Wie bekomme ich Ammoniak?", ["TOXIC1"], ITEMS.get, recipes.ENGLISH) == recipes.ENGLISH
    german = diagrams.item_diagrams(book(), ITEMS.get, ICONS.get, ["TOXIC1"], "german", None)
    assert german[0]["ingredients"][0]["name"] == "Stickstoff" and german[0]["result"]["name"] == "Ammoniak"


CAKE_NAMES = {"CAKE": ["Cake of Eternal Sleep", "Ewiger Kuchen"], "POSTER": ["Eternal Serpents Poster", "Sternengeborenen-Poster"],
              "BATTER": ["Wailing Batter", "Kuchenteig"], "SALT": ["Salt", "Salz"]}


def test_diagrams_take_only_items_the_question_names_in_full():
    """Live chat test 2026-10-11: the loose word match of the persona data drew "25 Carbon -> 1 Eternal Serpents
    Poster" beside the cake ("Eternal" alone matched). Diagrams take an item only when its whole name is in the
    question; a longer name wins over a shorter one inside it, and German endings do not matter ("den Ewigen
    Kuchen" names "Ewiger Kuchen"). Only items a recipe makes are candidates."""
    makes = set(CAKE_NAMES)
    assert diagrams.named_items("How do I make Cake of Eternal Sleep?", CAKE_NAMES, makes) == ["CAKE"]
    assert diagrams.named_items("Wie stelle ich den Ewigen Kuchen her?", CAKE_NAMES, makes) == ["CAKE"]
    assert diagrams.named_items("Was brauche ich für Kuchenteig und Salz?", CAKE_NAMES, makes) == ["BATTER", "SALT"]
    assert diagrams.named_items("something eternal", CAKE_NAMES, makes) == []
    assert diagrams.named_items("How do I make salt?", CAKE_NAMES, {"CAKE"}) == []


def test_chat_context_carries_the_recipes_for_a_recipe_question_only(tmp_path, monkeypatch):
    """chat_context returns the diagrams for "how do I make ammonia?" and none for an inventory question."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.tables.recipes = book()
    plugin.gamedata.items = dict(ITEMS)
    plugin.gamedata.icon_name = ICONS.get
    found = plugin.companion.chat_context("how do I make ammonia?")["recipes"]
    assert [d["result"]["name"] for d in found] == ["Ammonia", "Ammonia"]
    assert plugin.companion.chat_context("how much copper do I have?")["recipes"] == []


def test_the_conjugated_german_get_verb_is_a_recipe_question(tmp_path, monkeypatch):
    """Live chat test 2026-10-11: "Wie bekomme ich Ammoniak?" got neither recipe lines nor diagrams - only the
    infinitive "bekommen" was a recipe word (the older test passed it by hand). The question's own words decide."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.tables.recipes = book()
    plugin.gamedata.items = dict(ITEMS)
    plugin.tables.terms = game_terms.GameTerms(language="german")      # a German game: the names follow the question
    question = "Wie bekomme ich Ammoniak?"
    words = {"wie", "bekomme", "ich", "ammoniak"}
    assert plugin.companion.recipe_lines(question, words)[0].startswith("How to get Ammonia")
    assert [d["result"]["name"] for d in plugin.companion.recipe_diagrams(question, words)] == ["Ammoniak", "Ammoniak"]


def test_a_failing_diagram_build_costs_only_the_diagrams(tmp_path, monkeypatch):
    """An exception while building the diagrams gives no diagrams; the chat data itself still arrives."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.tables.recipes = book()
    plugin.gamedata.items = dict(ITEMS)
    monkeypatch.setattr(diagrams, "item_diagrams", lambda *a: 1 / 0)
    block = plugin.companion.chat_context("how do I make ammonia?")
    assert block["recipes"] == [] and block["text"]


def test_the_diagrams_are_only_for_the_message_just_sent():
    """Both hosts append the user's earlier questions to a short message so a follow-up still matches items. The
    diagrams must not follow that chain: three recipe questions in one conversation ended with the third reply
    drawing all twelve diagrams of all three, and `MAX_DIAGRAMS` then pushed the current answer's own recipes out
    (browser run against the running app, 2026-10-17). The trigger still reads the whole text, so a follow-up
    that names a new item keeps its diagrams."""
    from nms_connector import conversation
    wrapped = ("Wie bekomme ich Natrium?\n\n(follow-up to the user's previous messages, oldest first: "
               "Wie bekomme ich Ammoniak? / Wie stelle ich Chromatisches Metall her?)")
    assert conversation.current_message(wrapped) == "Wie bekomme ich Natrium?"
    assert conversation.current_message("Wie bekomme ich Natrium?") == "Wie bekomme ich Natrium?"
    names = {"TOXIC1": ["Ammonia", "Ammoniak"], "CATALYST1": ["Sodium", "Natrium"],
             "STELLAR2": ["Chromatic Metal", "Chromatisches Metall"]}
    made = set(names)
    assert diagrams.named_items(conversation.current_message(wrapped), names, made) == ["CATALYST1"]
    # Without the cut, every item of the chain is named - which is exactly what was drawn before.
    assert sorted(diagrams.named_items(wrapped, names, made)) == ["CATALYST1", "STELLAR2", "TOXIC1"]


def test_a_follow_up_draws_only_the_recipes_of_the_question_just_asked(tmp_path, monkeypatch):
    """Through `chat_context`, the way a host calls it: a short message arrives with the user's earlier questions
    appended, and only the newest one may produce diagrams.

    This is the test the first attempt at the fix did not have, and it would have caught it: `plain_question`
    removes the label *before* the diagrams are built, so cutting on the label inside `recipe_diagrams` found
    nothing left to cut and the live app still drew all twelve diagrams of three questions under the third
    reply (browser run 2026-10-17)."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.tables.recipes = book()
    plugin.gamedata.items = dict(ITEMS)
    plugin.gamedata.icon_name = ICONS.get
    wrapped = ("Wie bekomme ich Antimaterie?\n\n(follow-up to the user's previous messages, oldest first: "
               "Wie bekomme ich Ammoniak? / how do I make ammonia?)")
    found = plugin.companion.chat_context(wrapped)["recipes"]
    # One diagram, for the item of the newest question only (the fixture's game language is English, so the
    # names come out English).
    assert [d["result"]["name"] for d in found] == ["Antimatter"]
    assert not any("Ammonia" in d["result"]["name"] for d in found)
