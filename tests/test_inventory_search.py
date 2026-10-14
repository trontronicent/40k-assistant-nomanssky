"""Tests for the search across every inventory on the page (inventory_search.py, ConnectorPage, the action)."""

import asyncio
from types import SimpleNamespace

from nms_connector import create_plugin, inventory_search, planets_view
from test_connector import FakeCtx
from test_items import GameData as ItemsGameData


class GameData(ItemsGameData):
    """German game: names and categories in both languages (texts as the game writes them)."""
    items = {"YELLOW2": {"en": "Copper", "local": "Kupfer", "cat_en": "Metal Element", "cat_local": "Metallelement"},
             "EX_YELLOW": {"en": "Activated Copper", "local": "Aktiviertes Kupfer", "cat_en": "Metal Element"},
             "CAVE1": {"en": "Cobalt", "local": "Kobalt", "cat_en": "Metal Element"},
             "TRA_ALLOY1": {"en": "Aluminium", "local": "Aluminium", "cat_en": "Trade Goods (Construction)",
                            "cat_local": "Handelsgüter (Bau)", "value": 1000},
             "LAND1": {"en": "Ferrite Dust", "local": "Ferritstaub", "cat_en": "Basic Element"}}

    def lookup(self, item_id):
        return self.items.get(str(item_id).lstrip("^").split("#")[0])


def snapshot():
    """Copper in two storage containers and the freighter, a trade good on the ship, a corrupt id in the exosuit."""
    return {"exosuit": [["LAND1", 300, 500], ["\x00bad id", 1, 1]], "exosuit_cargo": [],
            "ships": [{"name": "Mad Falcon", "primary": True, "inventory": [["TRA_ALLOY1", 5, 10]]}],
            "freighter": {"name": "Kayani", "inventory": [["YELLOW2", 50, 9999]]},
            "storage": [{"number": 0, "key": "Chest1Inventory", "name": None,
                         "rows": [["YELLOW2", 581, 9999], ["EX_YELLOW", 103, 9999]]},
                        {"number": 7, "key": "Chest8Inventory", "name": "Metals", "rows": [["YELLOW2", 119, 9999]]}]}


def found(query):
    return [(h.place, h.item_id, h.amount) for h in inventory_search.search(snapshot(), query, GameData().lookup)]


def test_every_inventory_is_searched_by_name_in_either_language():
    """'Kupfer' and 'copper' both find every copper stack - storage, freighter - and Activated Copper (a word of its
    name); the matching is the planet search's (a word finds longer ones), so 'kupf' finds them too. The biggest
    stack comes first: the table is cut at MAX_ROWS, and the big stack answers "where is my copper"."""
    copper = [("Storage Container 0", "YELLOW2", 581), ("Storage Container 7 (Metals)", "YELLOW2", 119),
              ("Storage Container 0", "EX_YELLOW", 103), ("Freighter 'Kayani'", "YELLOW2", 50)]
    assert found("Kupfer") == copper and found("copper") == copper and found("kupf") == copper


def test_category_id_and_place_words_match_and_every_word_must():
    """The game's category in German ('Handelsgüter', typed with ue) finds the trade good on the ship; a word of
    its id works; a place word narrows ('copper freighter'), also in German ('Kupfer Frachter') or as 'ship'."""
    assert found("handelsgueter") == [("Starship 'Mad Falcon' (primary)", "TRA_ALLOY1", 5)]
    assert found("alloy") == [("Starship 'Mad Falcon' (primary)", "TRA_ALLOY1", 5)]      # only in its id
    assert found("copper freighter") == found("Kupfer Frachter") == [("Freighter 'Kayani'", "YELLOW2", 50)]
    assert found("ship") == [("Starship 'Mad Falcon' (primary)", "TRA_ALLOY1", 5)]
    assert found("copper cobalt") == [] and found("") == [] and found("ab") == []


def test_a_corrupt_id_and_a_missing_save_are_left_out():
    """The save holds the odd corrupt id (the persona drops it too); without a snapshot nothing is found."""
    assert all(h.item_id != "\x00bad id" for h in inventory_search.search(snapshot(), "bad", GameData().lookup))
    assert inventory_search.search(None, "copper", GameData().lookup) == []


def test_the_totals_line_adds_up_per_item_largest_first():
    """Above the table one line gives the total per item and in how many places it is, largest total first,
    so 'how much copper do I have' is answered without adding up rows."""
    hits = inventory_search.search(snapshot(), "kupfer", GameData().lookup)
    text = inventory_search.totals_text(hits, lambda i: GameData().lookup(i)["en"])
    assert text == "4 stack(s) of 2 item(s). Total: Copper 750 (3 places), Activated Copper 103."


def page_plugin(tmp_path, monkeypatch, query):
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.gamedata = GameData()
    plugin.snapshot = snapshot()
    plugin.inventory_query = query
    return plugin


def test_the_inventory_tab_has_the_search_form_and_results_with_their_inventory(tmp_path, monkeypatch):
    """The Inventory tab starts with the search form (keeping the query); the results table puts the item first
    (a phone titles each card by it), then an Inventory column, then the usual item columns."""
    plugin = page_plugin(tmp_path, monkeypatch, "Kupfer Frachter")
    ctx = SimpleNamespace(texts=planets_view.Texts(plugin.gamedata))
    form, totals, table, tabs = plugin.page.inventories(plugin.snapshot, ctx)
    assert form["action"] == inventory_search.SEARCH_INVENTORY and form["fields"][0]["value"] == "Kupfer Frachter"
    assert totals["text"].startswith("1 stack(s) of 1 item(s)") and tabs["id"] == "inventory-tabs"
    assert table["id"] == inventory_search.RESULTS_ID and table["title"] == "Items matching \"Kupfer Frachter\" (1)"
    assert table["columns"][:4] == ["Name (English)", "Name (Deutsch)", "Inventory", "Category"]
    row = table["rows"][0]
    assert row[0]["text"] == "Copper" and row[1:4] == ["Kupfer", "Freighter 'Kayani'", "Metal Element / Metallelement"]
    assert row[4:7] == ["YELLOW2", 50, 9999]


def test_without_a_query_only_the_form_is_shown(tmp_path, monkeypatch):
    """No query: just the form above the inventory tabs (no empty results table)."""
    plugin = page_plugin(tmp_path, monkeypatch, "")
    sections = plugin.page.inventories(plugin.snapshot, SimpleNamespace(texts=planets_view.Texts(plugin.gamedata)))
    assert [s["type"] for s in sections] == ["form", "tabs"]


def test_the_search_action_takes_untrusted_text_and_clears_with_an_empty_one(tmp_path, monkeypatch):
    """The form's value is cut to MAX_QUERY_CHARS, the reply says how many stacks match and focuses the results;
    an empty or missing value clears the search."""
    plugin = page_plugin(tmp_path, monkeypatch, "")
    result = asyncio.run(plugin.action(inventory_search.SEARCH_INVENTORY, {"query": "  kupfer "}))
    assert result == {"ok": True, "focus": inventory_search.RESULTS_ID, "message": "4 stack(s) match \"kupfer\"."}
    asyncio.run(plugin.action(inventory_search.SEARCH_INVENTORY, {"query": "x" * 500}))
    assert len(plugin.inventory_query) == inventory_search.MAX_QUERY_CHARS
    result = asyncio.run(plugin.action(inventory_search.SEARCH_INVENTORY, {"query": None}))
    assert result["message"] == "Inventory search cleared." and plugin.inventory_query == ""
