"""Recipes as structured data for the app's chat diagrams (diagrams.py, companion.recipe_diagrams): the model's own
wording could not be relied on (chat tests 2026-10-10/11), so chat_context hands the app the recipes as data."""

from nms_connector import diagrams, recipes
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


def test_a_failing_diagram_build_costs_only_the_diagrams(tmp_path, monkeypatch):
    """An exception while building the diagrams gives no diagrams; the chat data itself still arrives."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.tables.recipes = book()
    plugin.gamedata.items = dict(ITEMS)
    monkeypatch.setattr(diagrams, "item_diagrams", lambda *a: 1 / 0)
    block = plugin.companion.chat_context("how do I make ammonia?")
    assert block["recipes"] == [] and block["text"]
