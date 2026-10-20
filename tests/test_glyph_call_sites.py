"""Every place that shows a portal address also sends it as glyphs (planets_view, the overlay area)."""

from nms_connector import glyphs, planets_view
from nms_connector.history import PlanetHistory

EUCLID = 0x0620002925E80                   # RealityIndex 0
CALYPSO = 0x0620202925E80                  # RealityIndex 2


class Live:
    status, error, current, current_source = "ok", None, None, "planets"
    current_system = CALYPSO


class FakeTexts:
    def lookup(self, item_id):
        return {"en": item_id, "local": item_id}

    def icon_name(self, item_id):
        return None

    def text(self, key):
        return None


def context(tmp_path):
    history = PlanetHistory(tmp_path / "h.json")
    history.system_names = {EUCLID: "Delta Sol", CALYPSO: "Lipashc-Nogh"}
    return planets_view.Context(Live(), history, {EUCLID: {"planets": {}}, CALYPSO: {"planets": {}}},
                                FakeTexts(), None, bases=[])


def test_where_you_are_sends_the_address_as_glyphs(tmp_path):
    """The one place the player looks most: the address keeps its text and gains the symbols, so the page can
    draw the twelve glyphs the player types into a portal."""
    section = planets_view.where_you_are(context(tmp_path))
    item = next(i for i in section["items"] if i["label"] == "Portal address")
    assert item["glyphs"] == item["value"]
    assert glyphs.glyph_digits(item["glyphs"]) is not None


def test_the_system_map_star_sends_the_address_as_glyphs(tmp_path):
    """The star of a system map carries the same address, so it gets the same symbols."""
    section = planets_view.system_map(CALYPSO, context(tmp_path), "system-map", "System")
    item = next(i for i in section["center"]["items"] if i["label"] == "Portal address")
    assert item["glyphs"] == item["value"]


def test_an_item_without_an_address_sends_no_glyphs(tmp_path):
    """Only the address items gain the key; every other item is exactly what it was before this feature."""
    section = planets_view.where_you_are(context(tmp_path))
    for item in section["items"]:
        if item["label"] != "Portal address":
            assert "glyphs" not in item


def test_portal_item_and_cell_refuse_a_missing_address():
    """Without an address the helpers fall back to the plain placeholder and send no key, so a view can never
    ask the page to draw symbols for something that is not an address."""
    assert planets_view.portal_item("Portal address", None) == {"label": "Portal address", "value": "–"}
    assert planets_view.portal_cell(None) == "–"
    assert planets_view.portal_cell("not hex") == "not hex"
    assert planets_view.portal_cell("006202925E80") == {"text": "006202925E80", "glyphs": "006202925E80"}
