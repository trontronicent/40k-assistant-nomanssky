"""Copying any one inventory or loadout (exosuit, starship, freighter, multi-tool, exocraft - items or
installed technology), the generalisation of the ship and container exports."""
import asyncio
import json

import pytest

from nms_connector import equipment, page, place_export, toon

ITEMS = {"YELLOW2": {"en": "Copper", "value": 41}, "TRA_ALLOY1": {"en": "Aronium", "value": 1000},
         "UP_HYP4": {"en": "Hyperdrive Upgrade"}, "SHIELDBOOST": {"en": "Deflector Shield"}}

SNAP = {"exosuit": [["YELLOW2", 581, 9999]], "exosuit_cargo": [["TRA_ALLOY1", 3, 10]],
        "ships": [{"index": 0, "name": "Mad Falcon", "primary": True, "class": "S",
                   "inventory": [["YELLOW2", 12, 9999]]},
                  {"index": 2, "name": "", "primary": False, "class": "C", "inventory": []}],
        "freighter": {"name": "Hauler", "inventory": [["TRA_ALLOY1", 1, 10]]},
        "storage": []}

SHIPS = [{"index": 0, "name": "Mad Falcon", "type": "Fighter", "primary": True,
          "technology": [{"id": "UP_HYP4#66014", "charge": -1, "max": 0},
                         {"id": "SHIELDBOOST", "charge": 50, "max": 100}]},
         {"index": 2, "name": "", "type": "Hauler", "primary": False, "technology": []}]


class FakeTexts:
    def name(self, item_id):
        return (ITEMS.get(str(item_id).split("#", 1)[0]) or {}).get("en")

    def item(self, item_id, fallback=None):
        return self.name(item_id) or fallback or str(item_id)

    def category(self, item_id):
        return "Technology"

    def label(self, key):
        return None


def _equipment():
    """An Equipment as `from_save` builds it: the exosuit, one multi-tool in your hand, no exocraft."""
    return equipment.Equipment.from_save({"BaseContext": {"PlayerStateData": {
        "Inventory_TechOnly": {"Slots": [{"Type": {"InventoryType": "Technology"}, "Id": "^SHIELDBOOST",
                                          "Amount": 50, "MaxAmount": 100}]},
        "Multitools": [{"Resource": {"Filename": "tool.scene"}, "Name": "Lance",
                        "Store": {"Class": {"InventoryClass": "S"},
                                  "Slots": [{"Type": {"InventoryType": "Technology"}, "Id": "^UP_HYP4#66014",
                                             "Amount": -1}]}}],
        "ActiveMultioolIndex": 0,
        "FreighterInventory_TechOnly": {"Slots": []},
    }}})


def _places():
    return place_export.places(SNAP, SHIPS, _equipment(), FakeTexts())


def test_every_inventory_and_loadout_of_the_save_is_a_place_with_its_own_key():
    """Exosuit (with its cargo), every starship, the freighter, each ship's technology and the exosuit,
    multi-tool, exocraft and freighter loadouts are all copyable, each under a stable key - that is what makes
    the copy menu work on every table rather than only on the Ships and Storage ones."""
    keys = [p.key for p in _places()]
    assert keys == ["exosuit", "ship-0", "ship-2", "freighter",
                    "ship-0-tech", "ship-2-tech", "exosuit-tech", "multitool-0-tech", "freighter-tech"]
    kinds = {p.key: p.kind for p in _places()}
    assert kinds["exosuit"] == place_export.INVENTORY and kinds["multitool-0-tech"] == place_export.TECHNOLOGY


def test_an_inventory_carries_its_cargo_and_every_stack_with_its_base_value():
    """The exosuit place holds the suit *and* its cargo (the page shows them as one table), with the same item
    keys the container export writes, so one prompt can mix inventories from anywhere."""
    place = place_export.find(_places(), "exosuit")
    data = place_export.place_data(place, FakeTexts(), ITEMS.get)
    assert data["place"] == "Exosuit inventory" and data["kind"] == "inventory" and data["stacks"] == 2
    assert data["items"][0] == {"id": "YELLOW2", "name": "Copper", "amount": 581, "max": 9999,
                                "value_each": 41, "value_stack": 23821}
    assert data["value_total"] == 23821 + 3000


def test_a_loadout_carries_every_technology_with_its_charge():
    """A technology place lists each installed part with its category and charge; a part that needs no charge
    keeps None rather than the save's -1, which would read as a charge."""
    data = place_export.place_data(place_export.find(_places(), "multitool-0-tech"), FakeTexts(), ITEMS.get)
    assert data["kind"] == "technology" and data["installed"] == 1 and "Lance" in data["place"]
    assert data["technology"][0] == {"id": "UP_HYP4", "name": "Hyperdrive Upgrade", "category": "Technology",
                                     "charge": None, "max_charge": None, "damaged": False}
    ship_tech = place_export.place_data(place_export.find(_places(), "ship-0-tech"), FakeTexts(), ITEMS.get)
    assert ship_tech["technology"][1]["charge"] == 50 and ship_tech["technology"][1]["max_charge"] == 100


def test_the_rows_are_written_as_one_toon_table():
    """Every row of a place has the same keys, so TOON writes one header plus bare rows - where the format
    saves its tokens against JSON."""
    data = place_export.place_data(place_export.find(_places(), "exosuit"), FakeTexts(), ITEMS.get)
    text = toon.encode(data)
    assert "items[2]{id,name,amount,max,value_each,value_stack}:" in text
    assert len(text) < len(json.dumps(data, separators=(",", ":")))


def test_all_places_skip_the_empty_ones_and_name_them():
    """'Every inventory and loadout' writes only what holds something and names the empty places instead of
    writing empty lists, so the copied text stays worth a prompt."""
    data = place_export.all_data(_places(), FakeTexts(), ITEMS.get)
    assert [p["key"] for p in data["places"]] == ["exosuit", "ship-0", "freighter", "ship-0-tech",
                                                 "exosuit-tech", "multitool-0-tech"]
    assert "Freighter technology" in data["empty"] and place_export.entries(data) == 4 + 4


def test_the_menu_sits_on_every_row_of_a_place_but_not_on_a_left_click():
    """Each row of an inventory table carries that inventory's key, so a right-click anywhere in it copies the
    whole table; there is no `row_action`, because the rows are items and a left click must not copy by
    accident. An empty table still gets one key, or the menu would have none."""
    menu = place_export.menu_keys("exosuit", 2)
    assert menu["row_keys"] == ["exosuit", "exosuit"] and "row_action" not in menu
    assert [i["id"] for i in menu["row_menu"]] == list(place_export.EXPORT_ACTIONS)
    assert all(i["label"] and i["description"] for i in menu["row_menu"])
    assert place_export.menu_keys("exosuit", 0)["row_keys"] == ["exosuit"]


def test_the_technology_tables_of_the_equipment_tab_carry_the_menu():
    """Exosuit, multi-tool, exocraft and freighter technology are copyable from their own tables - without
    the menu the user would have to read the technology off the page. The tab's note says so, because the app
    draws a table's own `row_hint` only where its rows are clickable, and a technology row is not."""
    sections = equipment.equipment_sections(_equipment(), FakeTexts(), place_export.loadout_menu)
    tabs = {t["id"]: t for t in sections[0]["tabs"]}
    assert tabs["exosuit"]["sections"][0]["row_keys"] == ["exosuit-tech"]
    assert tabs["multitools"]["sections"][0]["row_keys"] == ["multitool-0-tech"]
    assert [i["id"] for i in tabs["freighter"]["sections"][0]["row_menu"]] == list(place_export.EXPORT_ACTIONS)
    assert "right-click" in sections[-1]["text"].lower()
    # Without a menu callable (an older caller) the tables stay exactly as they were.
    assert "row_menu" not in equipment.equipment_sections(_equipment(), FakeTexts())[0]["tabs"][0]["sections"][0]


def test_a_ships_technology_table_carries_the_menu():
    """The Ships & bases tab copies a ship's *technology* table too, not only the whole ship from the Ships
    table - the user asked for the inventory and the technology of each ship."""
    assert place_export.ship_tech_menu(SHIPS[0])["row_keys"] == ["ship-0-tech"] * 2


def test_a_copy_focuses_the_export_section_of_the_tab_it_was_made_in():
    """A ship's technology is copied under *Ships & bases* and every other place under *Inventory*, so each
    names its own export section: the app opens the tabs holding the section it focuses, and one shared id
    would drag the user out of the tab they were working in (seen in a headless run)."""
    assert place_export.section_id("ship-0-tech") == place_export.FLEET_EXPORT_ID
    for key in ("ship-0", "exosuit", "exosuit-tech", "multitool-0-tech", "freighter", ""):
        assert place_export.section_id(key) == place_export.EXPORT_ID
    assert place_export.export_section({"what": "x", "format": "TOON", "text": "t", "chars": 1},
                                       place_export.FLEET_EXPORT_ID)[0]["id"] == place_export.FLEET_EXPORT_ID


def _plugin(tmp_path, monkeypatch):
    from nms_connector import create_plugin
    from test_connector import FakeCtx
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.snapshot = dict(SNAP)
    plugin.ships = SHIPS
    plugin.equipment = _equipment()
    return plugin


def test_the_action_checks_its_key_and_answers_with_the_text(tmp_path, monkeypatch):
    """The key is untrusted: only a place of the newest save counts. A good one answers `copy` with the text
    and keeps it for the page (a browser without a secure context refuses the clipboard)."""
    plugin = _plugin(tmp_path, monkeypatch)
    for bad in ({}, {"key": "nonsense"}, {"key": "ship-9"}):
        assert plugin._export_place(place_export.EXPORT_TOON, bad)["ok"] is False
    assert plugin.place_export is None

    answer = plugin._export_place(place_export.EXPORT_JSON, {"key": " exosuit "})
    assert answer["ok"] and json.loads(answer["copy"])["key"] == "exosuit"
    assert answer["focus"] == place_export.EXPORT_ID
    assert plugin.place_export["format"] == "JSON" and plugin.place_export["text"] == answer["copy"]
    section = place_export.export_section(plugin.place_export)[0]
    assert section["id"] == place_export.EXPORT_ID and section["text"] == answer["copy"]
    # A ship's technology is shown under *Ships & bases*, so that copy focuses the fleet's own section - and a
    # padded key (the row menu hands back untrusted text) must still resolve to it.
    assert plugin._export_place(place_export.EXPORT_TOON, {"key": " ship-0-tech "})["focus"] == place_export.FLEET_EXPORT_ID


def test_copy_all_needs_no_key_and_refuses_an_empty_save(tmp_path, monkeypatch):
    """'Every inventory and loadout' ignores the row it was opened on, and says so plainly when nothing is
    stored anywhere."""
    plugin = _plugin(tmp_path, monkeypatch)
    answer = plugin._export_place(place_export.EXPORT_ALL_TOON, {"key": "exosuit"})
    assert answer["ok"] and "places[" in answer["copy"] and "entries)" in answer["message"]
    plugin.snapshot, plugin.ships, plugin.equipment = {}, [], None
    assert plugin._export_place(place_export.EXPORT_ALL_JSON, {})["ok"] is False


@pytest.mark.parametrize("action", place_export.EXPORT_ACTIONS)
def test_every_place_export_action_is_registered(action, tmp_path, monkeypatch):
    """Each menu entry is an action the connector answers - through `action()`, the way both hosts call it."""
    plugin = _plugin(tmp_path, monkeypatch)
    answer = asyncio.run(plugin.action(action, {"key": "exosuit"}))
    assert answer["ok"] and answer["copy"]


def test_the_inventory_tab_offers_the_menu_on_each_inventory_table(tmp_path, monkeypatch):
    """Exosuit, primary starship and freighter tables all carry their place's copy menu, and the copied text is
    shown once *above* the tabs - a browser outside a secure context cannot use the clipboard, and a copy made
    in one sub-tab must not drag the user into another (the app opens the tabs holding the focused section)."""
    plugin = _plugin(tmp_path, monkeypatch)
    plugin.place_export = {"what": "Exosuit inventory", "format": "TOON", "text": "x", "chars": 1}
    from test_connector import FakeCtx
    ctx = FakeCtx(tmp_path / "data")
    ctx.texts = FakeTexts()
    sections = page.ConnectorPage(plugin).inventories(plugin.snapshot, ctx)
    tabs = {t["id"]: t for t in sections[-1]["tabs"]}
    assert tabs["exosuit"]["sections"][-1]["row_keys"] == ["exosuit"] * 2
    assert tabs["starship"]["sections"][-1]["row_keys"] == ["ship-0"]
    assert tabs["freighter"]["sections"][-1]["row_keys"] == ["freighter"]
    # Exactly once, outside the tabs: inside every sub-tab the app's focus would jump to the first of them.
    assert [s.get("id") for s in sections].count(place_export.EXPORT_ID) == 1
    assert all(place_export.EXPORT_ID not in [s.get("id") for s in t["sections"]] for t in tabs.values())
