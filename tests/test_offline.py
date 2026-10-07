"""Working without the game files (store.py, GameTables stored mode, GameData.load_stored) and the persona answering
from stored data when the game is not running."""

import asyncio
import json

from nms_connector import cooking, seasons, store, tables
from nms_connector.gamedata import CACHE_FORMAT, GameData
from nms_connector.recipes import Recipe, RecipeBook
from test_connector import FakeCtx, create_plugin

ENGLISH = {"UI_SEASON_23_NAME": "Our Journey Continues", "UI_EXPED23_SUMMARY": "Time travel.",
           "LUSH1": "Lush Planet"}


def _book():
    return RecipeBook([Recipe("R1", "STEW", 1, (("VEG", 1), ("BEAN", 1)), True),
                       Recipe("R2", "AMMONIA", 1, (("TOXIC", 2), ("SALT", 1)), False)],
                      {"BOOK": [("PAPER", 3)]}, {"SALT"})


def test_the_recipe_book_survives_json():
    """to_json/from_json give back the same recipes (cooking flag, amounts), crafting requirements and substance ids -
    the stored book must answer exactly like the one read from the game files."""
    book = _book()
    again = RecipeBook.from_json(json.loads(json.dumps(book.to_json())))
    assert again.recipes == book.recipes and again.crafting == book.crafting and again.substances == book.substances
    assert RecipeBook.from_json({"recipes": "nonsense"}).error
    assert RecipeBook.from_json(None).error


def test_the_store_round_trips_and_ignores_damage(tmp_path):
    """TableStore writes atomically, reads back, and treats a missing, damaged or other-format file as 'nothing stored'
    instead of raising - a broken store must never stop the plugin."""
    s = store.TableStore(tmp_path)
    assert s.load() is None
    assert s.save("123", "german", _book().to_json(), {"english": ENGLISH, "local": None, "language": "german"})
    assert s.load()["build_id"] == "123"
    s.file.write_text("{ not json", encoding="utf-8")
    assert s.load() is None
    s.file.write_text(json.dumps({"format": 999}), encoding="utf-8")
    assert s.load() is None


def test_game_tables_load_from_the_store_when_the_game_files_are_missing(tmp_path):
    """Read once with the game (stored), then a fresh GameTables without an installation gets the recipes, the world
    types, the expeditions and the game terms back and says where they came from. This is the 'game is not
    installed here' case of 'use the persona with stored data'."""
    first = tables.GameTables(store.TableStore(tmp_path))
    first.build_id = "25732212"
    first.recipes = _book()
    first.ships = {"fixed": {"HYPERDRIVE": 100.0}, "procedural": {"UP_HYP4": (220, 265)}, "freighter_fixed": {},
                   "freighter_procedural": {}, "source": "game files"}
    first.settlements = {"source": "built-in (measured)"}          # a fallback is never stored
    first._build_texts(ENGLISH, {"UI_SEASON_23_NAME": "Unsere Reise geht weiter"}, "german", None)
    first._store(object(), ENGLISH, {"UI_SEASON_23_NAME": "Unsere Reise geht weiter"}, "german")

    offline = tables.GameTables(store.TableStore(tmp_path))
    warnings = offline.load(None)
    assert warnings == ["Game files not found: using the tables stored from game build 25732212"]
    assert offline.loaded and offline.stored_build == "25732212" and not offline.needs_load(None)
    assert len(offline.recipes.recipes) == 2 and offline.recipes.crafting == {"BOOK": [("PAPER", 3)]}
    assert offline.seasons.name(23) == "Our Journey Continues (Unsere Reise geht weiter)"
    assert offline.ships["fixed"] == {"HYPERDRIVE": 100.0} and list(offline.ships["procedural"]["UP_HYP4"]) == [220, 265]
    assert offline.settlements is None and offline.timers is None   # fallbacks were not stored: the built-ins stay
    assert offline.timer_durations and offline.settlement_rules


def test_without_a_store_the_tables_fall_back_as_before(tmp_path):
    """No installation and nothing stored: the same behaviour as before - fallback tables, an error naming the missing
    installation, no exception."""
    t = tables.GameTables(store.TableStore(tmp_path))
    warnings = t.load(None)
    assert t.loaded and t.stored_build is None and not t.recipes.recipes
    assert any("Recipes unavailable" in w for w in warnings) and not t.seasons.seasons


def test_nothing_is_stored_from_an_incomplete_read(tmp_path):
    """A read that found no recipes (a layout change) or no texts is not written over a good store."""
    t = tables.GameTables(store.TableStore(tmp_path))
    t.recipes = RecipeBook()
    t._store(object(), ENGLISH, None, "english")
    assert not t.store.file.exists()
    t.recipes = _book()
    t._store(None, ENGLISH, None, "english")
    t._store(object(), {}, None, "english")
    assert not t.store.file.exists()


def _item_cache(path, build="111", fmt=CACHE_FORMAT):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": fmt, "build_id": build, "language": "german",
                                "items": {"STEW": {"en": "Fibrous Stew", "value": 6400, "cat_en": "Edible Product"}}}), encoding="utf-8")


def test_the_item_database_can_be_adopted_without_the_game(tmp_path):
    """load_stored takes the cached item database whatever build it is from (the game is not there to compare),
    marks it stored, and refuses a cache of another format."""
    data = GameData(tmp_path)
    assert not data.load_stored()
    _item_cache(data.cache_file, fmt=CACHE_FORMAT - 1)
    assert not data.load_stored()
    _item_cache(data.cache_file)
    assert data.load_stored() and data.stored and data.ready and data.build_id == "111"
    assert data.lookup("STEW")["value"] == 6400


def test_the_persona_answers_from_stored_data_when_the_game_files_are_gone(tmp_path, monkeypatch):
    """The whole path: a plugin whose game cannot be found loads the item cache and the stored tables, and the
    persona still knows the dish's recipe, its value and the season - the game need not run, nor be installed."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    data_dir = tmp_path / "data"
    _item_cache(data_dir / "gamedata" / "items.json")
    seed = tables.GameTables(store.TableStore(data_dir))
    seed.build_id, seed.recipes = "111", _book()
    seed._build_texts(ENGLISH, None, "english", None)
    seed._store(object(), ENGLISH, None, "english")
    plugin = create_plugin(FakeCtx(data_dir))
    plugin.snapshot = {"location": {"galaxy": "Euclid", "portal": "0001"}, "bases": [], "units": 0, "nanites": 0,
                       "quicksilver": 0, "freighter": {"name": None}, "ships": [], "storage": [], "current_mission": None,
                       "saved_at": None, "exosuit": [["VEG", 1, 9], ["BEAN", 1, 9]], "exosuit_cargo": [],
                       "season": {"active": False, "number": None, "redeemed": 0}}

    asyncio.run(plugin._ensure_gamedata(force=True))

    assert plugin.install is None and plugin.gamedata.ready and plugin.tables.stored_build == "111"
    text = plugin.companion.chat_context("How do I cook Fibrous Stew?")["text"]
    assert "How to cook Fibrous Stew" in text and "6,400" in text and "you can cook it now with: VEG + BEAN" in text
    season = plugin.companion.chat_context("Which expedition is the newest season?")["text"]
    assert "Expedition 23" in season and "Our Journey Continues" in season
    assert cooking.DISH_CATEGORIES and seasons.RESEARCH_FILE.exists()
