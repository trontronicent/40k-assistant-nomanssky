"""The recipe viewer (recipe_view.py): the search, the automatic English/German switch, the page sections and the
overlay area - one builder for the app's page, the standalone page and both overlays."""

import asyncio
import pathlib

import pytest

from nms_connector import game_terms, recipe_view, recipes
from test_connector import FakeCtx, create_plugin
from test_recipes import ITEMS, book

ICONS = {"TOXIC1": "substance.biome.toxic.png", "GAS3": "gas.1.png"}


class FakeGameData:
    """What the viewer reads of the item database: names, icons and the other languages."""

    def __init__(self, items=None, icons=None, alt=None):
        self.items = dict(items if items is not None else ITEMS)
        self._icons = dict(icons or ICONS)
        self._alt = dict(alt or {})

    def lookup(self, item_id):
        return self.items.get(item_id)

    def icon_name(self, item_id):
        return self._icons.get(item_id)

    def alt_of(self, item_id):
        return self._alt.get(item_id, [])


def terms(language="german"):
    return game_terms.GameTerms(language=language)


def section(sections, **match):
    """The first section matching every given field (the host-visible shape, not an internal object)."""
    return next(s for s in sections if all(s.get(k) == v for k, v in match.items()))


def test_an_item_is_found_loosely_in_either_language():
    """A player types the way the game writes it, or short: "ferrit" and "ferrite" both find Ferrite Dust, an id
    finds its item, and a word matching nothing finds nothing. Matters because the search box is the only input
    of the whole viewer - a miss here means an empty page."""
    gd = FakeGameData()
    assert recipe_view.search(book(), gd.lookup, "ferrit", gd.alt_of) == ["LAND1"]
    assert recipe_view.search(book(), gd.lookup, "ferrite dust", gd.alt_of) == ["LAND1"]
    assert recipe_view.search(book(), gd.lookup, "TOXIC1", gd.alt_of) == ["TOXIC1"]
    assert recipe_view.search(book(), gd.lookup, "nothinglikethis", gd.alt_of) == []
    assert recipe_view.search(book(), gd.lookup, "", gd.alt_of) == []


def test_the_item_whose_name_was_spelled_out_comes_first():
    """"Salt" must answer with Salt, although "Crystal Sulphide" also holds no such word - a name the query spells
    out, then one it starts, ranks above a longer one, so the first (focused) result is the one meant."""
    gd = FakeGameData({**ITEMS, "SALT_BIG": {"en": "Salt Crystal", "local": "Salzkristall"}})
    assert recipe_view.search(book(), gd.lookup, "salt", gd.alt_of)[0] == "SALT"


def test_an_item_the_game_never_names_is_not_offered():
    """An id without any name would show as a bare id with nothing to read; it is skipped."""
    gd = FakeGameData({**ITEMS, "SULPHIDE": {}})
    assert "SULPHIDE" not in recipe_view.search(book(), gd.lookup, "sulphide", gd.alt_of)


def test_the_language_follows_what_was_typed():
    """The automatic switch: a German name gives German names, an English one English names, question words decide
    when the name itself cannot, and an English game stays English. This is the whole feature - the player sees the
    names their own game shows."""
    gd = FakeGameData()
    assert recipe_view.language_of("Ammoniak", ["TOXIC1"], gd.lookup, "german") == "german"
    assert recipe_view.language_of("Ammonia", ["TOXIC1"], gd.lookup, "german") == recipes.ENGLISH
    assert recipe_view.language_of("ferritstaub", ["LAND1"], gd.lookup, "german") == "german"
    assert recipe_view.language_of("wie mache ich antimaterie", ["ANTIMATTER"], gd.lookup, "german") == "german"
    assert recipe_view.language_of("Ammoniak", ["TOXIC1"], gd.lookup, recipes.ENGLISH) == recipes.ENGLISH


def test_an_english_name_wins_over_the_german_one_that_merely_starts_with_it():
    """Measured on the real item database (2026-10-18): "ammonia" also starts "Ammoniak", so counting word
    *starts* alone left the search undecided and answered a German player's English search in German. Whole
    words are counted first, which settles it; "Ammoniak" is still German, and a word that is only ever a
    prefix in both languages ("ferrit") falls through to the next rule."""
    gd = FakeGameData()
    assert recipe_view.language_of("ammonia", ["TOXIC1"], gd.lookup, "german") == recipes.ENGLISH
    assert recipe_view.language_of("ammoniak", ["TOXIC1"], gd.lookup, "german") == "german"
    assert recipe_view.language_of("ferrit", ["LAND1"], gd.lookup, "german") == "german"


def test_without_any_signal_the_game_s_own_language_wins():
    """An id, or a name both languages share, says nothing about the language. The player's game is German,
    so German is what they read on every item in it - answering such a search in English would be the odd
    one out. An English game stays English, since there is nothing else to offer."""
    gd = FakeGameData()
    assert recipe_view.language_of("TOXIC1", ["TOXIC1"], gd.lookup, "german") == "german"
    assert recipe_view.language_of("TOXIC1", ["TOXIC1"], gd.lookup, recipes.ENGLISH) == recipes.ENGLISH
    assert recipe_view.language_of("", [], gd.lookup, "german") == "german"


def test_the_sections_draw_every_recipe_that_makes_the_item():
    """A search gives what the item is, a `recipes` section with one diagram per recipe (refiner and Nutrient
    Processor), and what it is used in - the same diagram data the chat draws, so both look identical."""
    out = recipe_view.sections(book(), FakeGameData(), terms(), "ammonia", (recipe_view.SECTION_TYPE,))
    made = section(out, type="recipes", id=recipe_view.RESULTS_ID)
    assert made["title"] == "How to get Ammonia"
    assert made["recipes"][0]["ingredients"] == [{"amount": 1, "name": "Nitrogen", "icon": "gas.1.png"},
                                                 {"amount": 1, "name": "Di-hydrogen"}]
    assert made["recipes"][0]["result"] == {"amount": 1, "name": "Ammonia", "icon": "substance.biome.toxic.png"}
    assert made["recipes"][0]["station"].endswith("or larger")
    about = section(out, type="kv")
    assert {"label": "Id", "value": "TOXIC1"} in about["items"]
    assert about["title"] == "Ammonia"
    used = section(out, type="recipes", title="Ammonia is used in")
    # Refiner recipes first, then the Nutrient Processor ones - the order used_in answers in.
    assert "Toxic Stew" in [r["result"]["name"] for r in used["recipes"]]


def test_a_german_search_writes_the_whole_block_in_german():
    """"Ammoniak" gets German item names, the German station and the viewer's own German headings - a half-German
    diagram beside an English heading was the bug this switch exists to avoid."""
    out = recipe_view.sections(book(), FakeGameData(), terms(), "Ammoniak", (recipe_view.SECTION_TYPE,))
    made = section(out, type="recipes", id=recipe_view.RESULTS_ID)
    assert made["title"] == "So bekommst du Ammoniak"
    assert made["recipes"][0]["ingredients"][0]["name"] == "Stickstoff"
    assert made["recipes"][0]["result"]["name"] == "Ammoniak"
    assert "Raffinerie" in made["recipes"][0]["station"]


def test_a_host_that_cannot_draw_diagrams_gets_the_recipe_lines():
    """The section type is new; a host that does not list it (an older app, an older standalone page) still shows
    the viewer, as a list of recipe lines. Without this the tab would be blank there."""
    out = recipe_view.sections(book(), FakeGameData(), terms(), "ammonia", ())
    made = section(out, type="list", title="How to get Ammonia")
    assert made["items"][0].startswith("1 Nitrogen + 1 Di-hydrogen → 1 Ammonia · ")
    assert not [s for s in out if s["type"] == recipe_view.SECTION_TYPE]


def test_an_item_with_no_recipe_says_so_instead_of_showing_an_empty_block():
    """Copper is mined, not refined: the viewer says that in the search language rather than drawing nothing."""
    english = recipe_view.sections(book(), FakeGameData(), terms(), "copper", (recipe_view.SECTION_TYPE,))
    assert "gathered, mined or bought" in section(english, type="text", id=recipe_view.RESULTS_ID)["text"]
    german = recipe_view.sections(book(), FakeGameData(), terms(), "Kupfer", (recipe_view.SECTION_TYPE,))
    assert "gesammelt" in section(german, type="text", id=recipe_view.RESULTS_ID)["text"]


def test_an_empty_search_counts_the_recipes_and_a_missing_book_is_a_notice():
    """With no query the tab explains itself (and proves the recipes loaded); without a readable recipe table the
    user is told why the tab is empty instead of seeing a blank page."""
    idle = recipe_view.sections(book(), FakeGameData(), terms(), "", (recipe_view.SECTION_TYPE,))
    assert "recipes are loaded" in section(idle, type="text")["text"]
    broken = recipe_view.sections(recipes.RecipeBook(error="no game files"), FakeGameData(), terms(), "x", ())
    assert section(broken, type="notice")["text"].endswith("no game files")
    assert recipe_view.sections(None, FakeGameData(), terms(), "x", ())[1]["type"] == "notice"
    assert recipe_view.search_form("x")["fields"][0]["value"] == "x"


def test_a_search_with_no_hit_says_what_to_try():
    """A dead end must not look like a broken page."""
    out = recipe_view.sections(book(), FakeGameData(), terms(), "zzz", (recipe_view.SECTION_TYPE,))
    assert "No item matches" in section(out, type="text", id=recipe_view.RESULTS_ID)["text"]


def test_the_overlay_area_carries_the_diagrams_and_the_same_lines():
    """The overlay gets the identical recipe data (so it draws the same diagrams as the page and the chat) plus
    `lines` for an overlay that cannot draw them, and asks for its own search box."""
    area = recipe_view.overlay_area(book(), FakeGameData(), terms(), "ammonia")
    assert area["id"] == "recipes" and area["search"] is True and area["default_on"] is False
    assert area["query"] == "ammonia"
    assert area["recipes"][0]["result"]["name"] == "Ammonia"
    assert len(area["recipes"]) <= recipe_view.MAX_OVERLAY_RECIPES
    assert area["lines"][0].startswith("1 Nitrogen + 1 Di-hydrogen → 1 Ammonia")
    german = recipe_view.overlay_area(book(), FakeGameData(), terms(), "Ammoniak")
    assert german["recipes"][0]["result"]["name"] == "Ammoniak"


def test_the_overlay_area_explains_every_empty_case():
    """No query, no hit and no recipe book each get a line - an empty area in the overlay reads as "nothing to
    show yet", which would be wrong here."""
    gd, t = FakeGameData(), terms()
    assert recipe_view.overlay_area(book(), gd, t, "")["lines"] == ["Type an item name to see how it is made."]
    assert recipe_view.overlay_area(book(), gd, t, "zzz")["lines"] == ['Nothing matches "zzz".']
    assert recipe_view.overlay_area(None, gd, t, "x")["lines"][0].startswith("The recipes could not be read")
    assert recipe_view.overlay_area(book(), gd, t, "copper")["lines"][0].endswith("gathered, mined or bought.")


def _plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.tables.recipes = book()
    plugin.tables.terms = terms()
    plugin.gamedata.items = dict(ITEMS)
    plugin.gamedata.icon_name = ICONS.get
    plugin.ctx.section_types = (recipe_view.SECTION_TYPE, "form", "kv", "text", "list")
    return plugin


def test_the_search_action_stores_the_query_for_page_and_overlay(tmp_path, monkeypatch):
    """One action serves both: the Recipes tab's form and the overlay's box run `search_recipes`, and the next
    view *and* the next overlay poll are built from that one query - so they can never disagree."""
    plugin = _plugin(tmp_path, monkeypatch)
    result = asyncio.run(plugin.action(recipe_view.SEARCH_RECIPES, {"query": "Ammoniak"}))
    assert result["ok"] and result["focus"] == recipe_view.RESULTS_ID and "1 item(s)" in result["message"]
    assert plugin.recipe_query == "Ammoniak"
    tab = next(t for t in plugin.view()["sections"][-1]["tabs"] if t["id"] == "recipes")
    assert section(tab["sections"], type="recipes", id=recipe_view.RESULTS_ID)["recipes"][0]["result"]["name"] == "Ammoniak"
    area = next(a for a in plugin.overlay()["areas"] if a["id"] == "recipes")
    assert area["recipes"][0]["result"]["name"] == "Ammoniak"
    assert plugin.overlay()["recipe_search"] == recipe_view.SEARCH_RECIPES


def test_the_search_action_cuts_a_long_query_and_clears_on_empty(tmp_path, monkeypatch):
    """The query is untrusted input from a form or an overlay box: it is cut to the field's length, and an empty
    one clears the viewer rather than searching for nothing."""
    plugin = _plugin(tmp_path, monkeypatch)
    asyncio.run(plugin.action(recipe_view.SEARCH_RECIPES, {"query": "x" * 500}))
    assert len(plugin.recipe_query) == recipe_view.MAX_QUERY_CHARS
    assert asyncio.run(plugin.action(recipe_view.SEARCH_RECIPES, {}))["message"] == "Recipe search cleared."
    assert plugin.recipe_query == ""


def test_the_recipes_tab_works_before_a_save_has_been_read(tmp_path, monkeypatch):
    """The recipes come from the game's files, not from a save: the tab must be usable on a fresh install."""
    plugin = _plugin(tmp_path, monkeypatch)
    plugin.snapshot = None
    tab = next(t for t in plugin.view()["sections"][-1]["tabs"] if t["id"] == "recipes")
    assert tab["sections"][0]["id"] == recipe_view.FORM_ID


def _app_views():
    """The app's `plugins/views.py`, wherever the app is beside this checkout (`J:\\40k-assistant`) or above an
    installed plugin (`<app>/plugins/nomanssky`). Skips when the app is not there - the plugin repository must
    stay testable on its own."""
    import importlib.util
    import sys
    here = pathlib.Path(__file__).resolve()
    roots = [here.parents[2] / "40k-assistant", here.parents[3] / "40k-assistant", here.parents[2]]
    root = next((r for r in roots if (r / "src" / "plugins" / "views.py").is_file()), None)
    if root is None:
        pytest.skip("the app is not beside this checkout")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    spec = importlib.util.find_spec("src.plugins.views")
    if spec is None or not str(spec.origin).startswith(str(root)):
        pytest.skip("the app's views.py could not be imported")
    import src.plugins.views as views
    return views


@pytest.mark.parametrize("query", ["ammonia", "Ammoniak", ""])
def test_every_section_the_viewer_builds_is_one_the_app_accepts(query):
    """The app validates a plugin's view and refuses the whole thing on a bad section; checked here against the
    app's own `views.normalize_view` (and so against its new `recipes` type) so a change to either side fails this
    test rather than the live page."""
    views = _app_views()
    out = recipe_view.sections(book(), FakeGameData(), terms(), query, (recipe_view.SECTION_TYPE,))
    normalized = views.normalize_view({"title": "t", "sections": out}, "t")
    assert len(normalized["sections"]) == len(out)
    assert recipe_view.SECTION_TYPE in views.SECTION_TYPES
