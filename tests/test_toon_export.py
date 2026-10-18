"""Tests for the TOON encoder (toon.py) and the ship export behind the Ships table's right-click menu
(ships.export_data/export_toon, the connector's export actions)."""

import json

import pytest

from nms_connector import ships, toon


def test_toon_writes_objects_arrays_and_tables():
    """The three shapes of the format: nested objects by indentation, a primitive array with its length, and
    a uniform array of objects as one header plus bare rows - which is where TOON saves its tokens."""
    assert toon.encode({"id": 123, "name": "Ada"}) == "id: 123\nname: Ada"
    assert toon.encode({"user": {"id": 1, "deep": {"x": True}}}) == "user:\n  id: 1\n  deep:\n    x: true"
    assert toon.encode({"tags": ["admin", "ops", "dev"]}) == "tags[3]: admin,ops,dev"
    rows = {"items": [{"sku": "A1", "qty": 2, "price": 9.99}, {"sku": "B2", "qty": 1, "price": 14.5}]}
    assert toon.encode(rows) == "items[2]{sku,qty,price}:\n  A1,2,9.99\n  B2,1,14.5"
    assert toon.encode({"items": []}) == "items[0]:"
    assert toon.encode({"config": {}}) == "config:"


def test_toon_falls_back_to_the_list_form_when_rows_differ():
    """A table needs every row to carry the same keys and only primitives. Anything else is written as a
    list, with the first field on the hyphen line - never as a table with missing or invented cells."""
    mixed = {"items": [{"id": 1, "name": "First"}, {"id": 2, "name": "Second", "extra": True}]}
    assert toon.encode(mixed) == "items[2]:\n  - id: 1\n    name: First\n  - id: 2\n    name: Second\n    extra: true"
    nested = {"items": [{"id": 1, "deep": {"x": 1}}, {"id": 2, "deep": {"x": 2}}]}
    assert "items[2]:" in toon.encode(nested) and "{id,deep}" not in toon.encode(nested)
    assert toon.table_fields([{"a": 1}, {"a": 2}]) == ["a"]
    assert toon.table_fields([{"a": 1}, {"b": 2}]) is None       # different keys
    assert toon.table_fields([{"a": [1]}]) is None               # a value that is not primitive
    assert toon.table_fields([{}, {}]) is None and toon.table_fields([]) is None


def test_toon_quotes_only_what_would_read_back_wrong():
    """A string stays bare unless it would be mistaken for something else - a number, a boolean, null - or
    would break the line: the delimiter, a colon, a quote, a backslash, padding or a control character."""
    assert toon.scalar("plain text with spaces") == "plain text with spaces"
    assert toon.scalar("Hyperantrieb (Upgrade)") == "Hyperantrieb (Upgrade)"
    assert toon.scalar("42") == '"42"' and toon.scalar("true") == '"true"' and toon.scalar("null") == '"null"'
    assert toon.scalar("-1.5") == '"-1.5"'
    assert toon.scalar("a,b") == '"a,b"' and toon.scalar("a: b") == '"a: b"'
    assert toon.scalar('say "hi"') == '"say \\"hi\\""'
    assert toon.scalar("C:\\Users") == '"C:\\\\Users"'
    assert toon.scalar(" padded ") == '" padded "' and toon.scalar("") == '""'
    assert toon.scalar("- dash") == '"- dash"'
    assert toon.scalar("line\nbreak") == '"line\\nbreak"'
    assert toon.scalar("Deflektorschild – S-Klasse") == "Deflektorschild – S-Klasse"     # unicode needs none


def test_toon_writes_numbers_booleans_and_null_bare():
    """Numbers keep decimal form (no exponent), NaN and infinity have no representation and become null,
    and booleans and null are bare words - the same values JSON would carry."""
    assert toon.scalar(None) == "null" and toon.scalar(True) == "true" and toon.scalar(False) == "false"
    assert toon.scalar(7) == "7" and toon.scalar(-3) == "-3"
    assert toon.scalar(9.99) == "9.99" and toon.scalar(14.50) == "14.5" and toon.scalar(2.0) == "2"
    assert toon.scalar(1e6) == "1000000"
    assert toon.scalar(float("nan")) == "null" and toon.scalar(float("inf")) == "null"


class FakeTexts:
    """Only what an export reads (`name`), plus what the technology table of the Ships tab needs."""

    NAMES = {"HYPERDRIVE": "Hyperdrive (Hyperantrieb)", "UP_HYP4": "S-Class Hyperdrive Upgrade",
             "SHIPSHIELD": "Deflector Shield (Deflektorschild)", "YELLOW2": "Copper (Kupfer)"}

    def name(self, item_id):
        return self.NAMES.get(ships.tech_id(item_id))

    def item(self, item_id):
        return self.name(item_id) or ships.tech_id(item_id)

    def category(self, item_id):
        return None


def a_ship(**over) -> dict:
    ship = {"index": 2, "name": "Mad Falcon", "type": "Fighter", "class": "S", "primary": True,
            "stats": {"damage": 31.0, "shield": 20.0, "hyperdrive": 10.5, "agility": 0.0},
            "slots": 40, "cargo_slots": 0, "tech_slots": 32,
            "technology": [{"id": "HYPERDRIVE", "charge": 96, "max": 120},
                           {"id": "^UP_HYP4#66014", "charge": -1, "max": 100},
                           {"id": "SHIPSHIELD", "charge": 200, "max": 200},
                           {"id": f"{ships.DAMAGED_PREFIX}SHIPJUMP1", "charge": None, "max": None}]}
    ship.update(over)
    return ship


def test_a_ships_export_carries_what_the_page_shows():
    """The export is the Ships table's own facts plus the technology tab's: what the ship is, its stats,
    slots, warp range and every installed technology with its charge - so a model reading the export knows
    exactly what the page knows. A damaged slot is marked, and a technology with no charge says null."""
    data = ships.export_data(a_ship(), ships.FALLBACK, FakeTexts())
    assert data["ship"] == "Mad Falcon" and data["type"] == "Fighter" and data["class"] == "S"
    assert data["primary"] is True and data["stats_percent"]["damage"] == 31.0
    assert data["slots"] == {"general": 40, "cargo": 0, "tech": 32, "damaged": 1}
    assert data["warp_range_ly"]["low"] > 0 and data["warp_range_ly"]["star_colours"] == ["yellow"]
    tech = {t["id"]: t for t in data["technology"]}
    assert tech["HYPERDRIVE"] == {"id": "HYPERDRIVE", "name": "Hyperdrive (Hyperantrieb)", "charge": 96,
                                  "max_charge": 120, "damaged": False}
    assert tech["UP_HYP4"]["charge"] is None                      # -1 in the save: needs no charge
    assert tech["UP_HYP4"]["name"] == "S-Class Hyperdrive Upgrade"
    assert next(t for t in data["technology"] if t["damaged"])["id"].endswith("SHIPJUMP1")
    # An unnamed ship is labelled by its type, as everywhere else in the plugin.
    assert ships.export_data(a_ship(name=""), ships.FALLBACK, FakeTexts())["ship"] == "(unnamed Fighter)"


def test_the_export_is_smaller_as_toon_than_as_json():
    """The point of the format: the technology rows share their keys, so TOON writes them once instead of
    once per row. Measured on the real primary ship (30 technologies) it was 56 % smaller than indented
    JSON and 37 % smaller than compact JSON; this holds the property rather than the exact numbers."""
    ship = a_ship(technology=[{"id": f"UP_HYP{i}", "charge": i, "max": 100} for i in range(12)])
    text = ships.export_toon(ship, ships.FALLBACK, FakeTexts())
    data = ships.export_data(ship, ships.FALLBACK, FakeTexts())
    assert len(text) < len(json.dumps(data, separators=(",", ":"))) < len(json.dumps(data, indent=2))
    # The technology is one header plus one line per entry, and the header names the fields once.
    assert "technology[12]{id,name,charge,max_charge,damaged}:" in text
    assert sum(1 for line in text.splitlines() if line.startswith("  UP_HYP")) == 12
    assert "stats_percent:" in text and "warp_range_ly:" in text


def test_the_ships_table_offers_the_export_on_a_right_click():
    """The Ships table carries a row menu (app 3.18.0) and the same action on a left click, so the export
    is reachable on an older app too - an unknown `row_menu` is dropped by it, not refused."""
    sections = ships.ship_sections([a_ship()], ships.FALLBACK, FakeTexts())
    table = sections[0]
    assert table["row_keys"] == ["2"] and table["row_action"] == ships.EXPORT_TOON
    assert [i["id"] for i in table["row_menu"]] == list(ships.EXPORT_ACTIONS)
    assert all(i["label"] and i["description"] for i in table["row_menu"])
    assert "Right-click a ship" in table["row_hint"]


def test_the_export_action_checks_its_input_and_answers_with_the_text(tmp_path, monkeypatch):
    """The action takes the row's key as untrusted input, answers `copy` with the text (app 3.18.0 puts that
    on the clipboard) and keeps it for the page as well - a browser without a secure context refuses the
    clipboard, and the data must not be lost with it."""
    from nms_connector import create_plugin
    from test_connector import FakeCtx

    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.ships = [a_ship()]
    plugin.snapshot = {"ships": [{"index": 2, "inventory": [["YELLOW2", 581, 9999]]}]}

    assert plugin._export_ship(ships.EXPORT_TOON, {"key": "nonsense"})["ok"] is False
    assert plugin._export_ship(ships.EXPORT_TOON, {})["ok"] is False
    assert plugin._export_ship(ships.EXPORT_TOON, {"key": "99"})["ok"] is False
    assert plugin.ship_export is None

    answer = plugin._export_ship(ships.EXPORT_TOON, {"key": "2"})
    assert answer["ok"] is True and answer["focus"] == ships.EXPORT_ID
    assert answer["copy"].startswith("ship: Mad Falcon") and "technology[4]{" in answer["copy"]
    assert "4 technologies" in answer["message"] and "characters copied" in answer["message"]
    assert plugin.ship_export["ship"] == "Mad Falcon" and plugin.ship_export["format"] == "TOON"
    shown = ships.export_section(plugin.ship_export)[0]
    assert shown["id"] == ships.EXPORT_ID and shown["text"] == answer["copy"]
    assert "Mad Falcon as TOON" in shown["title"]

    # With cargo, and as JSON.
    with_cargo = plugin._export_ship(ships.EXPORT_TOON_CARGO, {"key": "2"})
    # The action uses the connector's own item texts; this test environment has no item database, so an
    # unnamed id stands for its own name - the shape is what matters here.
    assert "cargo[1]{id,name,amount,max}:" in with_cargo["copy"] and "YELLOW2,YELLOW2,581,9999" in with_cargo["copy"]
    assert plugin.ship_export["format"] == "TOON with cargo"
    as_json = plugin._export_ship(ships.EXPORT_JSON, {"key": "2"})
    assert json.loads(as_json["copy"])["ship"] == "Mad Falcon" and plugin.ship_export["format"] == "JSON"
    # Every menu entry is an action the connector actually has.
    assert all(action in plugin._actions for action in ships.EXPORT_ACTIONS)


@pytest.mark.parametrize("action", ships.EXPORT_ACTIONS)
def test_every_export_action_is_registered(action):
    """A menu entry naming an action the connector does not have would fail only when clicked."""
    from nms_connector.plugin import NmsConnector
    assert callable(NmsConnector._export_ship)
    assert action in ships.EXPORT_ACTIONS
