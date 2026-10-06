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


def test_an_items_document_says_where_it_comes_from_every_recipe_and_its_uses():
    """Asked for 2026-10-06 ("Ammoniak: findable and every recipe that creates it"): the document carries both
    names, where the game says it is found (English and German), each refiner recipe with the refiner size it
    needs, and what it is used for; a gathered-only substance says so; a product gets its crafting recipe."""
    b = book()
    doc = recipes.item_markdown(b, ITEMS.get, "TOXIC1")
    assert 'title: "Ammonia (Ammoniak)"' in doc and recipes.GENERATED_MARK in doc
    assert "## Where it comes from (Fundort)" in doc and "toxic environment" in doc and "Deutsch: Ist auf Planeten" in doc
    assert ("- 2 Fungal Mould (Pilzschimmel) + 1 Salt (Salz) → 1 Ammonia (Ammoniak) · Medium or Large Refiner"
            in doc)
    assert "- 1 Ammonia (Ammoniak) → 1 Ferrite Dust (Ferritstaub) · any Refiner" in doc
    assert "For cooking (1):" in doc and "Nutrient Processor" in doc
    copper = recipes.item_markdown(b, ITEMS.get, "YELLOW2")
    assert "gathered (mined, harvested or collected) only" in copper
    anti = recipes.item_markdown(b, ITEMS.get, "ANTIMATTER")
    assert "## About (Beschreibung)" in anti
    assert "- 25 Chromatic Metal + 20 Condensed Carbon → 1 Antimatter (Antimaterie)" in anti


def test_documents_go_to_category_folders_and_unnamed_ids_are_skipped():
    """Raw materials, products and foods get their own folder; a title with characters Windows forbids gets a
    safe file name; ids without an English name (unused by the game) get no document."""
    docs = recipes.documents(book(), ITEMS.get)
    assert "Items/Raw materials/Ammonia (Ammoniak).md" in docs
    assert "Items/Products/Antimatter (Antimaterie).md" in docs and "Items/Food/Toxic Stew.md" in docs
    assert "Items/Products/Crystal Sulphide.md" in docs
    assert recipes.file_name('Upgrade: "A/B"?') == "Upgrade AB.md"
    no_names = recipes.documents(book(), {}.get)
    assert no_names == {}


def test_writing_touches_only_generated_files(tmp_path):
    """New and changed documents are written, unchanged ones left alone (the Codex sync skips them), generated
    files no longer produced are removed - and a hand-written file with the same name is never overwritten."""
    folder = tmp_path / "No Man's Sky"
    docs = recipes.documents(book(), ITEMS.get)
    assert recipes.write_documents(folder, docs)["written"] == len(docs)
    assert recipes.write_documents(folder, docs) == {"written": 0, "unchanged": len(docs), "removed": 0,
                                                     "kept_handwritten": 0}
    own = folder / "Items" / "Raw materials" / "Salt (Salz).md"
    own.write_text("# Salt\nMy own notes.", encoding="utf-8")
    stale = folder / "Items" / "Products" / "Gone.md"
    stale.write_text(f"---\n# {recipes.GENERATED_MARK}\n---\nold", encoding="utf-8")
    counts = recipes.write_documents(folder, docs)
    assert counts["kept_handwritten"] == 1 and counts["removed"] == 1 and not stale.exists()
    assert own.read_text(encoding="utf-8") == "# Salt\nMy own notes."
    assert (folder / "FAQ").exists() is False        # nothing outside Items/ is created or removed


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
