"""Cooking for the persona (cooking.py) and its use in the companion: folded ingredient pools, what can be cooked
from the player's holdings, base values of items, and what the inventory is worth."""

import itertools


from nms_connector import assistant, cooking
from nms_connector.recipes import Recipe, RecipeBook
from test_connector import FakeCtx, create_plugin


def _cook(rid, result, *ingredients):
    return Recipe(rid, result, 1, tuple((i, 1) for i in ingredients), True)


def _label(item):
    return item.title()


def _unfold(entries):
    """Every ingredient combination (as a frozenset-like sorted tuple) an `pools` result stands for."""
    out = set()
    for kind, groups in entries:
        if kind == "one":
            out |= {(i,) for i in groups[0]}
        elif kind == "two":
            out |= {tuple(sorted(c)) for c in itertools.combinations_with_replacement(groups[0], 2)}
        elif kind == "pair":
            out |= {tuple(sorted((a, b))) for a in groups[0] for b in groups[1]}
        else:
            out.add(tuple(sorted(g[0] for g in groups)))
    return out


def test_pools_fold_the_pairs_of_a_dish_without_losing_or_inventing_a_combination():
    """33 pairs of one stew fold into a few pool entries that unfold to exactly the original recipes: the pairs of
    {A, B, C} (repeats included), each of them with D, and E + D. The persona gets short lines, but a folded
    line must never promise a combination the game does not have."""
    pairs = list(itertools.combinations_with_replacement(["a", "b", "c"], 2)) + [("a", "d"), ("b", "d"), ("c", "d"), ("e", "d")]
    recs = [_cook(f"R{k}", "STEW", *p) for k, p in enumerate(pairs)]
    entries = cooking.pools(recs)
    assert _unfold(entries) == {tuple(sorted(p)) for p in pairs}
    assert len(entries) < len(recs)


def test_pools_keep_single_and_triple_ingredient_recipes():
    """One-ingredient recipes become an "any one" entry and three-ingredient ones are listed as they are, so no
    recipe shape is dropped."""
    recs = [_cook("1", "X", "p"), _cook("2", "X", "q"), _cook("3", "X", "a", "b", "c")]
    kinds = {k for k, _ in cooking.pools(recs)}
    assert kinds == {"one", "all"}
    assert _unfold(cooking.pools(recs)) == {("p",), ("q",), ("a", "b", "c")}


def test_a_shared_pool_is_spelled_out_once():
    """A pool used by two entries (or longer than three names) gets a letter and one definition line, so the long
    ingredient names are not repeated for every partner."""
    pairs = list(itertools.combinations_with_replacement(["a", "b", "c", "d"], 2)) + [("a", "z"), ("b", "z"), ("c", "z"), ("d", "z")]
    lines = cooking.fold_lines(cooking.pools([_cook(str(k), "S", *p) for k, p in enumerate(pairs)]), _label)
    assert sum(1 for line in lines if line.startswith("pool A =")) == 1
    assert any("pool A + Z" in line or "Z + pool A" in line for line in lines)


def test_cookable_needs_every_ingredient_in_amount_and_ranks_by_value():
    """A dish is cookable only when all its ingredients are held; the same ingredient twice needs two; the result
    lists the most valuable dish first and says how many times it can run. This is the "best recipe I can cook now"
    answer, so a dish with a missing ingredient must never appear."""
    book = RecipeBook([_cook("1", "CHEAP", "milk"), _cook("2", "RICH", "egg", "milk"), _cook("3", "TWICE", "egg", "egg")])
    value = {"CHEAP": 100, "RICH": 900, "TWICE": 5000}.get
    got = cooking.cookable(book, {"milk": 4, "egg": 1}, value)
    assert [e["dish"] for e in got] == ["RICH", "CHEAP"]
    assert got[0]["times"] == 1 and got[1]["times"] == 4
    assert [e["dish"] for e in cooking.cookable(book, {"egg": 2}, value)] == ["TWICE"]
    assert cooking.cookable(book, {}, value) == []


def _lines(question, have, named, book=None):
    book = book or RecipeBook([_cook("1", "STEW", "veg", "bean"), _cook("2", "CAKE", "egg", "milk")])
    value = {"STEW": 6400, "CAKE": 90000}.get
    view = cooking.CookingView(book, have, _label, value, {"facts": ["Cooked in a Nutrient Processor."]})
    return cooking.cooking_lines(view, question, named)


def test_a_question_that_is_not_about_cooking_gets_no_cooking_block():
    """"How much Copper do I have?" must not drag a cooking block (and its characters) into the data."""
    assert _lines("How much copper do I have?", {"veg": 1}, ["COPPER"]) == []


def test_a_named_dish_gets_its_ingredients_and_what_you_can_cook_now():
    """"How do I make Stew?" names the dish, gives the value and the combinations, and says whether the player
    holds a complete combination."""
    text = "\n".join(_lines("How do I make Stew?", {"veg": 1, "bean": 1}, ["STEW"]))
    assert "How to cook Stew" in text and "6,400" in text and "Veg + Bean" in text
    assert "you can cook it now with: Veg + Bean" in text
    lacking = "\n".join(_lines("How do I make Stew?", {"veg": 1}, ["STEW"]))
    assert "nothing you hold" in lacking


def test_best_dish_question_lists_what_can_be_cooked_and_what_is_missing():
    """"best cooking recipe I can make right now" lists the dishes cookable from the holdings and the game's most
    valuable dishes with the ingredients still missing - never an invented ingredient list."""
    text = "\n".join(_lines("What is the best cooking recipe I can make right now?", {"veg": 1, "bean": 1}, []))
    assert "Best dish you can cook right now: Stew: 6,400 units each, up to 1 time (6,400 units in all) - Veg + Bean" in text
    assert "The most valuable dish in the game is Cake: 90,000 units each" in text and "you lack Egg, Milk" in text


def test_an_ingredient_question_lists_the_dishes_it_goes_into():
    """"What can I cook with veg?" names an ingredient: the dishes that use it, the valuable ones first."""
    text = "\n".join(_lines("What can I cook with veg?", {"veg": 1}, ["veg"]))
    assert "Veg is an ingredient of 1 dishes" in text and "Stew (6,400 units each) with Bean" in text


def test_cooking_is_added_to_the_persona_data_for_a_cooking_question(tmp_path, monkeypatch):
    """chat_context carries the Cooking block (with the recipe book and the holdings) for a cooking question and
    the item's base value for an item question; a dish no refiner makes is "cooked", not "gathered only"."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.snapshot = {"location": {"galaxy": "Euclid", "portal": "0001"}, "bases": [], "units": 0, "nanites": 0,
                       "quicksilver": 0, "freighter": {"name": None}, "ships": [], "storage": [], "current_mission": None,
                       "saved_at": None, "exosuit": [["VEG", 2, 100], ["BEAN", 1, 100], ["COPPER", 50, 9999]],
                       "exosuit_cargo": []}
    plugin.gamedata.items = {"STEW": {"en": "Fibrous Stew", "value": 6400, "cat_en": "Edible Product"},
                             "VEG": {"en": "Veg Root", "cat_en": "Raw Ingredient"},
                             "BEAN": {"en": "Impulse Bean", "cat_en": "Raw Ingredient"},
                             "COPPER": {"en": "Copper", "value": 100, "cat_en": "Raw"}}
    plugin.tables.recipes = RecipeBook([_cook("1", "STEW", "VEG", "BEAN")])
    text = plugin.companion.chat_context("How do I cook a Fibrous Stew?")["text"]
    assert "Cooking (the Nutrient Processor" in text and "Veg Root + Impulse Bean" in text
    assert "cooked in the Nutrient Processor" in "\n".join(plugin.companion.recipe_lines("how do I make Fibrous Stew", {"how", "make"}))
    assert "Cooking (the Nutrient Processor" not in plugin.companion.chat_context("How much Copper do I have?")["text"]
    assert "base value 100 units each, 5,000 for your 50" in plugin.companion.chat_context("How much Copper do I have?")["text"]


def test_value_note_tells_unsellable_from_unknown():
    """A base value of 0 says the item cannot be sold; an item in no value table says nothing (unknown); a stack
    shows the total. The persona must not answer "worth 0" for something the game has not priced."""
    assert assistant.value_note(None) == ""
    assert "cannot be sold" in assistant.value_note(0)
    assert assistant.value_note(3280, 3) == "base value 3,280 units each, 9,840 for your 3 (before an economy's price factor)"


def test_inventory_worth_sums_stacks_by_place_and_names_the_top_items():
    """What the inventories are worth: the total at base value, per place, the most valuable items across places and
    how many stacks have no sell value. Answers "how much is my whole inventory worth?"."""
    snap = {"exosuit": [["GEODE", 3, 5], ["JUNK", 10, 10]], "exosuit_cargo": [["GEODE", 2, 5], ["BAD ID!", 1, 1]],
            "freighter": {"inventory": [["COPPER", 100, 9999]]}, "ships": [], "storage": []}
    value = {"GEODE": 3280, "COPPER": 100}.get
    text = "\n".join(assistant.inventory_worth(snap, value, lambda i: i.title()))
    assert "total 26,400 units over 4 stacks" in text and "1 stacks have no sell value" in text
    assert "Geode: 16,400 (5 x 3,280)" in text
    assert assistant.inventory_worth(None, value, str) == []


def test_worth_question_adds_the_inventory_worth_unless_it_names_one_item(tmp_path, monkeypatch):
    """"What is my whole inventory worth?" gets the worth block; "What is a Geode worth?" gets the item's own value
    line instead (no inventory-wide block)."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.snapshot = {"location": {"galaxy": "Euclid", "portal": "0001"}, "bases": [], "units": 0, "nanites": 0,
                       "quicksilver": 0, "freighter": {"name": None}, "ships": [], "storage": [], "current_mission": None,
                       "saved_at": None, "exosuit": [["GEODE", 3, 5]], "exosuit_cargo": []}
    plugin.gamedata.items = {"GEODE": {"en": "Geode", "value": 3280}}
    whole = plugin.companion.chat_context("How much is my whole inventory worth?")["text"]
    one = plugin.companion.chat_context("What is a Geode worth?")["text"]
    assert "Inventory worth at the game's base value" in whole and "total 9,840 units" in whole
    assert "Inventory worth at the game's base value" not in one and "base value 3,280 units each" in one


def test_request_filler_names_no_item():
    """"best recipe I can execute right now" named the "Liquidator Right Arm" (the word "right") and made the persona
    print three unrelated 'how to get' blocks. Filler words of a request are stopwords, real item words still match."""
    names = {"ARM": ["Liquidator Right Arm"], "MILK": ["Fresh Milk"], "STEW": ["Fibrous Stew"]}
    assert assistant.match_items("Give me the best cooking recipe I can execute with the materials right now", names) == []
    assert assistant.match_items("What is the most valuable dish worth right now?", names) == []
    assert assistant.match_items("How do I cook a Fibrous Stew?", names, whole_only=True) == ["STEW"]
    assert assistant.match_items("how much milk do I have", names) == ["MILK"]


def test_the_cheapest_dishes_and_the_total_earnings_are_shown():
    """"What is the cheapest dish I can cook?" lists the cookable dishes from the bottom, and every cookable dish says
    what all the runs together are worth (value x times) - the persona had only the top of the list and answered
    that it did not have the cheapest dish."""
    book = RecipeBook([_cook("1", "CHEAP", "milk"), _cook("2", "MID", "egg"), _cook("3", "RICH", "veg")])
    value = {"CHEAP": 100, "MID": 900, "RICH": 5000}.get
    view = cooking.CookingView(book, {"milk": 4, "egg": 1, "veg": 2}, _label, value)
    lines = cooking.cooking_lines(view, "What is the cheapest dish I can cook right now?", [])
    text = chr(10).join(lines)
    assert "The cheapest dishes you can cook right now (of 3; cheapest first): Cheap: 100 units each, up to 4 times (400 units in all)" in text
    assert "Best dish you can cook right now: Rich: 5,000 units each, up to 2 times (10,000 units in all)" in text


def test_dishes_of_equal_value_are_listed_in_a_stable_order():
    """Two dishes worth the same were listed in whatever order a set iterated in, so the persona's data changed from run
    to run (the most valuable dish flipped between two equal ones). Ties are now broken by id."""
    book = RecipeBook([_cook(str(k), name, "x", f"y{k}") for k, name in enumerate(["B", "A", "D", "C"])])
    view = cooking.CookingView(book, {}, _label, {"A": 100, "B": 100, "C": 100, "D": 100}.get)
    lines = cooking._most_valuable_lines(view)
    assert lines[0].startswith("  The most valuable dish in the game is A:") and lines[1].index("B:") < lines[1].index("C:")
