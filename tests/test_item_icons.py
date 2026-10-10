"""item_icons(): the plugin's name -> icon-file-name map for the app's chat-diagram feature (app 3.17.0)."""
from test_connector import FakeCtx

from nms_connector import create_plugin


def test_item_icons_maps_every_name_form_with_a_real_icon(tmp_path):
    """An item with a converted icon is mapped under its English name, its local name (when different), and the
    combined "English (Local)" label; an item without an icon is absent entirely."""
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.gamedata.items = {
        "SUBSTANCE_AMMONIA": {"en": "Ammonia", "local": "Ammoniak"},
        "SUBSTANCE_COPPER": {"en": "Copper", "local": "Copper"},   # local == en: only two forms
        "SUBSTANCE_NOICON": {"en": "Ghost Item", "local": "Ghost Item"},   # no converted icon at all
    }
    plugin.gamedata.icon_name = lambda item_id: {
        "SUBSTANCE_AMMONIA": "substance.fuel.1.png",
        "SUBSTANCE_COPPER": "substance.metal.1.png",
    }.get(item_id)

    icons = plugin.item_icons()

    assert icons["Ammonia"] == "substance.fuel.1.png"
    assert icons["Ammoniak"] == "substance.fuel.1.png"
    assert icons["Ammonia (Ammoniak)"] == "substance.fuel.1.png"
    assert icons["Copper"] == "substance.metal.1.png"
    assert "Copper (Copper)" not in icons
    assert "Ghost Item" not in icons
