"""Recipes from the game's files (recipes.py): the refiner/cooking table, crafting requirements, the recipe book,
the Codex documents written from it and the persona's recipe lines."""

import struct

import pytest

from nms_connector import mbin, recipes

ROOT, START = 0x10, 0x20


def _element(item: str, amount: int, kind: int = 0) -> bytes:
    return item.encode().ljust(0x10, b"\0") + struct.pack("<ii", amount, kind)


def recipe_table(rows) -> bytes:
    """A GcRefinerRecipe table: rows = (id, (result, amount, kind), [(ingredient, amount, kind)], cooking)."""
    size = recipes.RECORD
    data = bytearray(START + size * len(rows))
    struct.pack_into("<QI4s", data, ROOT, START - ROOT, len(rows), mbin.MARK)
    tail = bytearray()
    for k, (rid, result, ingredients, cooking) in enumerate(rows):
        base = START + k * size
        data[base:base + len(rid)] = rid.encode()
        data[base + recipes.RESULT_AT:base + recipes.RESULT_AT + recipes.ELEMENT] = _element(*result)
        target = len(data) + len(tail)
        header = base + recipes.INGREDIENTS_AT
        struct.pack_into("<QI4s", data, header, target - header, len(ingredients), mbin.MARK)
        tail += b"".join(_element(*i) for i in ingredients)
        struct.pack_into("<fB", data, base + recipes.TIME_AT, 90.0, int(cooking))
    return bytes(data + tail)


def product_table(rows, size=0x60, id_at=0x10, req_at=0x30) -> bytes:
    """A product table: rows = (id, [(ingredient, amount)]); the requirement list header at req_at."""
    data = bytearray(START + size * len(rows))
    struct.pack_into("<QI4s", data, ROOT, START - ROOT, len(rows), mbin.MARK)
    tail = bytearray()
    for k, (pid, req) in enumerate(rows):
        base = START + k * size
        data[base + id_at:base + id_at + len(pid)] = pid.encode()
        target = len(data) + len(tail)
        struct.pack_into("<QI4s", data, base + req_at, target - (base + req_at), len(req), mbin.MARK)
        tail += b"".join(_element(i, a) for i, a in req)
    return bytes(data + tail)


RECIPES = recipe_table([
    ("REFINERECIPE_1", ("TOXIC1", 1, 0), [("PLANT_TOXIC", 2, 0), ("SALT", 1, 0)], False),
    ("REFINERECIPE_2", ("TOXIC1", 1, 0), [("GAS3", 1, 0), ("GAS2", 1, 0)], False),
    ("REFINERECIPE_3", ("LAND1", 1, 0), [("TOXIC1", 1, 0)], False),
    ("REFINERECIPE_4", ("CATALYST2", 50, 0), [("SULPHIDE", 1, 2)], False),
    ("RECIPE_5", ("FOOD_STEW", 1, 2), [("TOXIC1", 1, 0), ("FOOD_MEAT", 1, 2), ("SALT", 1, 0)], True),
])

ITEMS = {
    "TOXIC1": {"en": "Ammonia", "local": "Ammoniak", "cat_en": "Localised Earth Element",
               "desc_en": "Typically found on planets with a toxic environment.",
               "desc_local": "Ist auf Planeten mit toxischem Klima zu finden."},
    "PLANT_TOXIC": {"en": "Fungal Mould", "local": "Pilzschimmel"}, "SALT": {"en": "Salt", "local": "Salz"},
    "GAS3": {"en": "Nitrogen", "local": "Stickstoff"}, "GAS2": {"en": "Di-hydrogen", "local": "Diwasserstoff"},
    "LAND1": {"en": "Ferrite Dust", "local": "Ferritstaub"}, "CATALYST2": {"en": "Sodium Nitrate"},
    "SULPHIDE": {"en": "Crystal Sulphide"}, "FOOD_STEW": {"en": "Toxic Stew"}, "FOOD_MEAT": {"en": "Meat"},
    "ANTIMATTER": {"en": "Antimatter", "local": "Antimaterie", "desc_en": "Contained negative matter."},
    "STELLAR2": {"en": "Chromatic Metal"}, "FUEL2": {"en": "Condensed Carbon"},
    "YELLOW2": {"en": "Copper", "local": "Kupfer", "desc_en": "Copper is found on planets orbiting yellow stars."},
}


def book() -> recipes.RecipeBook:
    return recipes.RecipeBook(recipes.parse_recipes(RECIPES), {"ANTIMATTER": [("STELLAR2", 25), ("FUEL2", 20)]},
                              {"TOXIC1", "PLANT_TOXIC", "SALT", "GAS3", "GAS2", "LAND1", "CATALYST2", "YELLOW2"})


def test_recipe_table_reads_result_ingredients_amounts_and_cooking():
    """Each record's result, ingredients with amounts (amount before inventory type: Crystal Sulphide is a product,
    type 2) and the Nutrient Processor flag are read as the game stores them."""
    rs = recipes.parse_recipes(RECIPES)
    assert [(r.result, r.amount, r.ingredients, r.cooking) for r in rs[:2]] == [
        ("TOXIC1", 1, (("PLANT_TOXIC", 2), ("SALT", 1)), False), ("TOXIC1", 1, (("GAS3", 1), ("GAS2", 1)), False)]
    assert rs[3].ingredients == (("SULPHIDE", 1),) and rs[3].amount == 50 and rs[4].cooking is True


def test_a_moved_layout_gives_no_recipes_rather_than_wrong_ones():
    """Records of another size, or results that are not item ids, raise: nothing is guessed from a game update
    that moved the fields."""
    with pytest.raises(mbin.MbinError):
        recipes.parse_recipes(product_table([("A", [("B", 1)])]))
    broken = bytearray(RECIPES)
    for k in range(5):
        broken[START + k * recipes.RECORD + recipes.RESULT_AT:START + k * recipes.RECORD + recipes.RESULT_AT + 4] = b"\xff" * 4
    with pytest.raises(mbin.MbinError):
        recipes.parse_recipes(bytes(broken))


def test_crafting_requirements_are_found_by_calibration():
    """The item id field and the requirement list are found from known ids, wherever the layout puts them
    (Antimatter = 25 Chromatic Metal + 20 Condensed Carbon)."""
    known = {"ANTIMATTER", "STELLAR2", "FUEL2", "WARPCELL", "AM_HOUSING"}
    rows = [("ANTIMATTER", [("STELLAR2", 25), ("FUEL2", 20)]), ("WARPCELL", [("AM_HOUSING", 1), ("ANTIMATTER", 1)])]
    for id_at, req_at in ((0x10, 0x30), (0x40, 0x20)):
        assert recipes.parse_requirements(product_table(rows, id_at=id_at, req_at=req_at), known) == {
            "ANTIMATTER": [("STELLAR2", 25), ("FUEL2", 20)], "WARPCELL": [("AM_HOUSING", 1), ("ANTIMATTER", 1)]}
    with pytest.raises(mbin.MbinError):
        recipes.parse_requirements(product_table(rows), {"NOTHING"})


def test_the_book_answers_what_makes_an_item_and_what_it_is_used_for():
    """made_by lists the refiner recipes (cooking apart), used_in the refiner, crafting and cooking uses;
    items() covers every item any recipe names."""
    b = book()
    assert [r.id for r in b.made_by("TOXIC1")] == ["REFINERECIPE_2", "REFINERECIPE_1"]     # 1 of 2 beats 1 of 3
    assert [r.id for r in b.made_by("FOOD_STEW", cooking=True)] == ["RECIPE_5"] and b.made_by("FOOD_STEW") == []
    uses = b.used_in("TOXIC1")
    assert [r.result for r in uses["refiner"]] == ["LAND1"] and [r.result for r in uses["cooking"]] == ["FOOD_STEW"]
    assert b.used_in("STELLAR2")["crafting"] == ["ANTIMATTER"]
    assert {"TOXIC1", "SULPHIDE", "FUEL2", "FOOD_MEAT"} <= b.items()


def terms():
    """The game's terms as read from a German game (game_terms fallbacks, language german)."""
    from nms_connector import game_terms
    return game_terms.GameTerms(language="german")


def test_an_items_document_says_where_it_comes_from_every_recipe_and_its_uses():
    """Asked for 2026-10-06 ("Ammoniak: findable and every recipe that creates it"), then split by language: the
    English document is English only - where the game says it is found, each refiner recipe with the smallest
    refiner that has enough slots (the game's names), its uses - and names the item once in German."""
    b = book()
    doc = recipes.item_markdown(b, ITEMS.get, "TOXIC1", "english", terms())
    assert 'title: "Ammonia"' in doc and "language: en" in doc and recipes.GENERATED_MARK in doc
    assert "## Where it comes from" in doc and "toxic environment" in doc and "Ist auf Planeten" not in doc
    assert "- 2 Fungal Mould + 1 Salt → 1 Ammonia · Medium Refiner or larger" in doc
    assert "- 1 Ammonia → 1 Ferrite Dust · Portable Refiner or larger" in doc
    assert "For cooking (1):" in doc and "Nutrient Processor" in doc and "In the German game: Ammoniak." in doc
    copper = recipes.item_markdown(b, ITEMS.get, "YELLOW2", "english", terms())
    assert "gathered (mined, harvested or collected) only" in copper
    anti = recipes.item_markdown(b, ITEMS.get, "ANTIMATTER", "english", terms())
    assert "## About" in anti and "- 25 Chromatic Metal + 20 Condensed Carbon → 1 Antimatter" in anti


def test_the_german_document_uses_the_games_german_words():
    """The German document has German names, the German description and the game's own German terms (Mittlere
    Raffinerie, Nährstoffprozessor - not 'Nahrungsprozessor' as before), and names the item once in English."""
    doc = recipes.item_markdown(book(), ITEMS.get, "TOXIC1", "german", terms())
    assert 'title: "Ammoniak"' in doc and "language: de" in doc and "## Fundort" in doc
    assert "Ist auf Planeten mit toxischem Klima zu finden." in doc and "toxic environment" not in doc
    assert "- 2 Pilzschimmel + 1 Salz → 1 Ammoniak · Mittlere Raffinerie oder größer" in doc
    assert "Nährstoffprozessor" in doc and "Nahrungsprozessor" not in doc
    assert "## Verwendet für" in doc and "Im Spiel auf Englisch: Ammonia." in doc


def test_documents_go_to_language_and_category_folders_and_unnamed_ids_are_skipped():
    """Per language a folder named as the language calls itself, categories as the game names them (Raw
    Materials / Rohstoffe, Products / Produkte, Food / Nahrung); ids without an English name get no document; a
    title with characters Windows forbids gets a safe file name; an English game gets English documents only."""
    docs = recipes.documents(book(), ITEMS.get, terms())
    assert "English/Raw Materials/Ammonia.md" in docs and "Deutsch/Rohstoffe/Ammoniak.md" in docs
    assert "English/Products/Antimatter.md" in docs and "Deutsch/Produkte/Antimaterie.md" in docs
    assert "English/Food/Toxic Stew.md" in docs and "Deutsch/Nahrung/Toxic Stew.md" in docs
    assert "English/Products/Crystal Sulphide.md" in docs
    assert recipes.file_name('Upgrade: "A/B"?') == "Upgrade AB.md"
    assert recipes.documents(book(), {}.get, terms()) == {}
    from nms_connector import game_terms
    english_only = recipes.documents(book(), ITEMS.get, game_terms.GameTerms(language="english"))
    assert all(p.startswith("English/") for p in english_only)


def test_writing_touches_only_generated_files(tmp_path):
    """New and changed documents are written, unchanged ones left alone (the Codex sync skips them), generated
    files no longer produced are removed - also the mixed-language ones of the old layout - and a hand-written
    file is never overwritten or removed."""
    folder = tmp_path / "No Man's Sky"
    docs = recipes.documents(book(), ITEMS.get, terms())
    dirs = ("English", "Deutsch") + recipes.LEGACY_DIRS
    assert recipes.write_documents(folder, docs, recipes.GENERATED_MARK, dirs)["written"] == len(docs)
    assert recipes.write_documents(folder, docs, recipes.GENERATED_MARK, dirs) == {
        "written": 0, "unchanged": len(docs), "removed": 0, "kept_handwritten": 0}
    own = folder / "English" / "Raw Materials" / "Salt.md"
    own.write_text("# Salt\nMy own notes.", encoding="utf-8")
    legacy = folder / "Items" / "Raw materials" / "Ammonia (Ammoniak).md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(f"---\n# {recipes.GENERATED_MARK}\n---\nold", encoding="utf-8")
    counts = recipes.write_documents(folder, docs, recipes.GENERATED_MARK, dirs)
    assert counts["kept_handwritten"] == 1 and counts["removed"] == 1
    assert not (folder / "Items").exists()                 # emptied legacy folders go too
    assert own.read_text(encoding="utf-8") == "# Salt\nMy own notes."


def test_no_game_gives_an_empty_book_with_a_reason():
    """Without an installation the book is empty and says why (GameTables reports it as a fallback warning)."""
    b = recipes.load(None)
    assert b.recipes == [] and b.error == "game installation not found"


def test_the_persona_gets_recipes_when_the_question_asks_how_to_get_an_item(tmp_path, monkeypatch):
    """A question about getting an item ("Wie bekomme ich Ammoniak?") adds where it comes from and its recipes to
    the chat data; a question that only names the item (an inventory count) does not."""
    from test_connector import FakeCtx, create_plugin
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.tables.recipes = book()
    plugin.gamedata.items = dict(ITEMS)
    lines = plugin.companion.recipe_lines("Wie bekomme ich Ammoniak?", {"wie", "bekomme", "ich", "ammoniak", "bekommen"})
    assert lines[0] == "How to get Ammonia (Ammoniak) (from the game's files):"
    assert any("toxic environment" in line for line in lines)
    assert any(line.startswith("  refiner: 2 Fungal Mould (Pilzschimmel) + 1 Salt (Salz) → 1 Ammonia") for line in lines)
    assert plugin.companion.recipe_lines("How much Ammonia do I have?", {"how", "much", "ammonia", "do", "i", "have"}) == []
    copper = plugin.companion.recipe_lines("where do I find copper", {"where", "do", "i", "find", "copper"})
    assert copper[-1] == "  no refiner or crafting recipe makes it: it is gathered only"


def test_an_item_that_is_no_raw_material_is_not_called_gathered(tmp_path, monkeypatch):
    """Chat test 2026-10-09: 'how do I get the Pulse Engine?' was answered 'gathered only, no crafting recipe'. An item
    without a recipe that is not in the substance table (a technology, a reward) gets a line that forbids 'gathered';
    a raw material (Copper) keeps 'gathered only'. Why: the model repeated the plugin's false claim to the player."""
    from test_connector import FakeCtx, create_plugin
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.tables.recipes = book()
    plugin.gamedata.items = dict(ITEMS, PULSE={"en": "Pulse Engine", "desc_en": "Faster travel within a system."})
    lines = plugin.companion.recipe_lines("how do I get the Pulse Engine?", {"how", "do", "i", "get", "the", "pulse", "engine"})
    assert lines[0].startswith("How to get Pulse Engine")
    assert "do not say it is gathered" in lines[-1] and "gathered only" not in lines[-1]
    copper = plugin.companion.recipe_lines("where do I find copper", {"where", "do", "i", "find", "copper"})
    assert copper[-1].endswith("it is gathered only")


def test_recipes_for_a_misspelt_item_and_the_split_german_verb(tmp_path, monkeypatch):
    """Chat of 2026-10-09: 'wie stelle ich Paraphine her?' and 'how do I create Paraphenium?' got no recipes - the
    split verb 'stelle ... her' and 'create' were no recipe words, and the misspelt name matched no item. Now both
    give the item's recipes, with the name read by sound ('Ammoniack' and 'Amonia' -> Ammonia)."""
    from test_connector import FakeCtx, create_plugin
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.tables.recipes = book()
    plugin.gamedata.items = dict(ITEMS)
    for question in ("wie stelle ich Ammoniack her?", "how do I create Amonia?"):
        words = set(question.lower().rstrip("?").split())
        lines = plugin.companion.recipe_lines(question, words)
        assert lines and lines[0] == "How to get Ammonia (Ammoniak) (from the game's files):", question


def test_the_codex_tool_finds_the_item_cache_installed_or_beside_a_checkout(tmp_path):
    """Run from the installed plugin (plugins/nomanssky) the cache is plugins/.data/nomanssky; run from a
    development checkout beside the app it is the app's - the old default only worked for the checkout."""
    installed = tmp_path / "app" / "plugins" / "nomanssky" / "nms_connector" / "recipes.py"
    cache = tmp_path / "app" / "plugins" / ".data" / "nomanssky" / "gamedata" / "items.json"
    cache.parent.mkdir(parents=True)
    cache.write_text("{}")
    assert recipes.default_items_path(installed) == cache.resolve()
    checkout = tmp_path / "stc-repos" / "plugin" / "nms_connector" / "recipes.py"
    app_cache = tmp_path / "40k-assistant" / "plugins" / ".data" / "nomanssky" / "gamedata" / "items.json"
    app_cache.parent.mkdir(parents=True)
    app_cache.write_text("{}")
    assert recipes.default_items_path(checkout) == app_cache.resolve()


def test_item_tooltips_say_how_to_get_the_item():
    """The plugin page's item tooltip gets a 'How to get it:' block from the game's recipe table: the best refiner
    recipes with the refiner they need (at most HOW_TO_GET_RECIPES, the rest pointed to the Codex) and the
    crafting recipe; nothing without a recipe book."""
    from types import SimpleNamespace
    from nms_connector import planets_view
    gd = SimpleNamespace(lookup=ITEMS.get, recipes=book(), terms=None)
    texts = SimpleNamespace(gamedata=gd)
    how = planets_view.Texts.how_to_get(texts, "TOXIC1", limit=1)
    assert how.startswith("How to get it:\n• 1 Nitrogen + 1 Di-hydrogen → 1 Ammonia · Medium Refiner or larger")
    assert "… 1 more refiner recipe (Codex" in how
    anti = planets_view.Texts.how_to_get(texts, "ANTIMATTER")
    assert anti == "How to get it:\n• Crafted from 25 Chromatic Metal + 20 Condensed Carbon"
    assert planets_view.Texts.how_to_get(SimpleNamespace(gamedata=SimpleNamespace(lookup=ITEMS.get)), "TOXIC1") is None


def test_the_codex_library_folder_is_found_as_the_app_finds_it(tmp_path):
    """$CODEX_FOLDER wins (trimmed, as the app trims it); else knowledge_base/ in the app folder, two levels above
    the installed plugin (<app>/plugins/nomanssky)."""
    plugin_root = tmp_path / "app" / "plugins" / "nomanssky"
    assert recipes.codex_library_folder(plugin_root, {}) == (tmp_path / "app" / "knowledge_base" / "No Man's Sky").resolve()
    assert recipes.codex_library_folder(plugin_root, {"CODEX_FOLDER": f"  {tmp_path / 'kb'} "}) == tmp_path / "kb" / "No Man's Sky"


def test_the_write_codex_action_writes_both_languages(tmp_path, monkeypatch):
    """The page's 'Write Codex documents' writes the item and world documents of both languages into the Codex
    library folder and tells to press Sync now; before the game files are read it says so instead."""
    import asyncio
    from test_connector import FakeCtx, create_plugin
    from nms_connector import game_terms, worlds
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("CODEX_FOLDER", str(tmp_path / "kb"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    early = asyncio.run(plugin.action("write_codex", {}))
    assert early["ok"] is False and "not written" in early["message"]
    plugin.tables.loaded = True
    plugin.tables.recipes = book()
    plugin.tables.terms = game_terms.GameTerms(language="german")
    plugin.tables.worlds = worlds.WorldBook.from_texts({"DEAD9": "Airless %PLANETCLASS%", "WEATHER_DEAD7": "Airless"},
                                                      {"DEAD9": "Stickiger %PLANETCLASS%", "WEATHER_DEAD7": "Stickig"}, "german")
    plugin.gamedata.items = dict(ITEMS)
    done = asyncio.run(plugin.action("write_codex", {}))
    assert done["ok"] and "Sync now" in done["message"]
    library = tmp_path / "kb" / "No Man's Sky"
    assert (library / "Deutsch" / "Rohstoffe" / "Ammoniak.md").is_file()
    assert (library / "English" / "Raw Materials" / "Ammonia.md").is_file()
    assert (library / "Deutsch" / "Welten" / "Stickige Welten (tot, ohne Atmosphäre).md").is_file()
