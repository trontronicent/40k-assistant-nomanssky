"""Tests for item tooltips (category, description, where trade goods sell) and storage containers."""

from nms_connector import galaxy, planets_view, summary, trade
from nms_connector.history import PlanetHistory

HERE = 0x620002925E80
NEAR = 0x630002935E80           # a nearby region
FAR = 0x640002A25E80


class Live:
    status, error, current, current_source, current_system = "ok", None, None, "planets", HERE


class GameData:
    ready, language, language_label = True, "german", "Deutsch"
    trading = dict(trade.FALLBACK)
    trading_source = "built-in"
    items = {"TRA_ALLOY1": {"en": "Aluminium", "local": "Aluminium", "cat_en": "Trade Commodity",
                            "cat_local": "Handelsware", "desc_en": "A light metal."},
             "FUEL1": {"en": "Carbon", "local": "Kohlenstoff", "cat_en": "Fuel Element"}}

    def lookup(self, item_id):
        return self.items.get(str(item_id).lstrip("^").split("#")[0])

    def icon_name(self, item_id):
        return "x.png" if item_id == "FUEL1" else None

    def text(self, key):
        return None


def economy_for(category, role):
    """The economy class that needs (role 'needs') or sells (role 'sells') a trade-goods category."""
    return next(e for e, t in trade.FALLBACK.items() if t[role] == category)


def context(tmp_path, economies):
    history = PlanetHistory(tmp_path / "h.json")
    history.economies = economies
    return planets_view.Context(Live(), history, {NEAR: {"name": "Market"}}, GameData(), None)


def test_trade_goods_are_recognised_by_their_id():
    """TRA_<CATEGORY><tier> ids map to their category; other ids (and seeded variants) do not."""
    assert trade.category_of("^TRA_ALLOY3") == "Alloy" and trade.category_of("TRA_MINERALS1") == "Mineral"
    assert trade.category_of("FUEL1") is None and trade.category_of("TRA_ALLOYX") is None and trade.category_of(None) is None


def test_trade_good_tooltip_names_buyers_and_the_nearest_known_one(tmp_path):
    """The tooltip says which economies pay well (with the price factor), the nearest known system of such an
    economy with its distance, how many more are known, and where the good is cheap to buy."""
    buyer, seller = economy_for("Alloy", "needs"), economy_for("Alloy", "sells")
    ctx = context(tmp_path, {NEAR: {"economy": buyer, "wealth": "Wealthy"}, FAR: {"economy": buyer},
                             HERE: {"economy": seller}})
    cell = ctx.texts.item("TRA_ALLOY1")
    lines = cell["hint"].split("\n")
    assert lines[0] == "Category: Trade Commodity / Handelsware" and "A light metal." in lines
    assert any(line.startswith("Sell at: ") and "they pay x" in line for line in lines)
    assert f"Known system that buys it: Market - {galaxy.distance_text(galaxy.distance_ly(HERE, NEAR))} (Wealthy)." in lines
    assert "(1 more known; see Systems -> Trade.)" in lines
    assert lines[-1].startswith("Cheap to buy at: ") and lines[-1].endswith("nearest known: System 006202925E80 - you are there.")


def test_trade_good_tooltip_says_when_no_buyer_is_known(tmp_path):
    """Without a known system of a buying economy, the tooltip says so and how economies get read."""
    hint = context(tmp_path, {}).texts.hint("TRA_ALLOY1")
    assert "You have not found such a system yet" in hint and "Cheap to buy at:" in hint


def test_ordinary_items_get_category_and_description_only(tmp_path):
    """A resource's tooltip holds its category; unknown items keep a plain id and category stays empty."""
    texts = context(tmp_path, {}).texts
    assert texts.item("FUEL1") == {"text": "Carbon (Kohlenstoff)", "icon": "x.png", "hint": "Category: Fuel Element"}
    assert texts.item("NOPE") == "NOPE" and texts.category("NOPE") is None


def test_storage_containers_are_numbered_like_the_game():
    """Chest1..Chest10 are the game's containers 0-9 (empty ones listed too); other storages appear only when
    they hold something; freighter cargo joins the freighter."""
    slot = lambda i, n: {"Id": f"^{i}", "Amount": n, "MaxAmount": 9999, "Type": {"InventoryType": "Substance"}}
    ps = {f"Chest{n}Inventory": {"Name": "BLD_STORAGE_NAME", "Slots": []} for n in range(1, 11)}
    ps["Chest1Inventory"]["Slots"] = [slot("FUEL1", 18)]
    ps["Chest8Inventory"]["Slots"] = [slot("STELLAR2", 469)]
    ps["ChestMagicInventory"] = {"Slots": [slot("STELLAR2", 15)]}
    ps["ChestMagic2Inventory"] = {"Slots": []}
    ps["FreighterInventory"] = {"Slots": [slot("FUEL1", 1)]}
    ps["FreighterInventory_Cargo"] = {"Slots": [slot("CATALYST1", 5)]}
    snap = summary.summarize({"BaseContext": {"PlayerStateData": ps}})
    chests = snap["storage"]
    assert [c["number"] for c in chests] == list(range(10)) + [None]
    assert chests[0]["rows"] == [["FUEL1", 18, 9999]] and chests[7]["rows"] == [["STELLAR2", 469, 9999]]
    assert chests[10]["key"] == "ChestMagicInventory"
    assert [r[0] for r in snap["freighter"]["inventory"]] == ["FUEL1", "CATALYST1"]


def test_storage_tab_lists_full_containers_and_names_the_empty_ones(tmp_path, monkeypatch):
    """The Storage tab has one table per container that holds something, titled with the game's number (a
    renamed container also shows its name), other storages by save key, and a line naming the empty ones."""
    from nms_connector import create_plugin
    from test_connector import FakeCtx
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    snap = {"storage": [{"number": 0, "key": "Chest1Inventory", "name": "BLD_STORAGE_NAME", "rows": [["FUEL1", 18, 9999]]},
                        {"number": 1, "key": "Chest2Inventory", "name": "BLD_STORAGE_NAME", "rows": []},
                        {"number": 7, "key": "Chest8Inventory", "name": "Metals", "rows": [["STELLAR2", 469, 9999]]},
                        {"number": None, "key": "ChestMagicInventory", "name": None, "rows": [["STELLAR2", 15, 9999]]}]}
    tab = plugin._storage_tab(snap, context(tmp_path, {}), ["Name", "Category", "Item id", "Amount", "Max"])
    titles = [s.get("title") for s in tab["sections"]]
    assert titles[:3] == ["Storage Container 0 - 1 stacks", "Storage Container 7: Metals - 1 stacks",
                          "Other storage (ChestMagic) - 1 stacks"]
    assert tab["sections"][0]["rows"][0][:3] == [{"text": "FUEL1", "icon": "x.png", "hint": "Category: Fuel Element"},
                                                 "Fuel Element", "FUEL1"]
    assert tab["sections"][-1]["text"] == "Empty storage containers: 1." and tab["badge"] == 3
