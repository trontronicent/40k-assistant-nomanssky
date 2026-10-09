"""Tests for the Equipment tab: exosuit, multi-tools, exocraft and freighter technology from the save."""

from nms_connector import equipment


def tech(tid, amount=-1, maximum=100):
    return {"Type": {"InventoryType": "Technology"}, "Id": f"^{tid}", "Amount": amount, "MaxAmount": maximum}


def save():
    """Kay's equipment on 2026-10-04/05 (trimmed): exosuit parts, two used multi-tools and three unused entries
    (no model), the active one at index 2 ("ActiveMultioolIndex", spelled so in the save), a freighter drive, and
    exocraft by GcVehicleType: the Roamer (index 0, summoned first) with parts, an empty Nomad, the unused
    hovercraft slot (4) and the Minotaur (6)."""
    unused = {"Name": "", "Resource": {"Filename": ""}, "Store": {"Class": {"InventoryClass": "C"}}}
    vehicle = lambda *ids: {"Inventory_TechOnly": {"Slots": [tech(i) for i in ids]}}     # noqa: E731
    return {"BaseContext": {"PlayerStateData": {
        "Inventory_TechOnly": {"Slots": [tech("PROTECT", 80, 100), tech("UP_JET1#50161")]},
        "Inventory": {"Slots": [{"Type": {"InventoryType": "Substance"}, "Id": "^FUEL1"}]},
        "ActiveMultioolIndex": 2,
        "Multitools": [
            {"Name": "Shitttool", "Resource": {"Filename": "MULTITOOL.SCENE.MBIN"},
             "Store": {"Class": {"InventoryClass": "B"}, "Slots": [tech("LASER", 42)]}},
            unused,
            {"Name": "Quantum Kay Needler", "Resource": {"Filename": "MULTITOOL.SCENE.MBIN"},
             "Store": {"Class": {"InventoryClass": "A"}, "Slots": [tech("UP_LASER1#53433"), tech("TERRAINEDITOR", 562, 600)]}},
            unused],
        "PrimaryVehicle": 0,
        "VehicleOwnership": [vehicle("VEHICLE_ENGINE", "UP_EXGUN1#59766"), vehicle(), {}, {}, vehicle("VEHICLE_ENGINE"),
                             {}, vehicle("MECH_ENGINE")],
        "FreighterInventory_TechOnly": {"Slots": [tech("F_HYPERDRIVE", 96, 120)]}}}}


def test_equipment_is_read_with_the_multitool_in_your_hand_first():
    """Only technology slots count (not the fuel in the general inventory); unused multi-tool entries are
    skipped; the active one comes first and is marked; exocraft without technology and the game's unused
    hovercraft slot are left out."""
    eq = equipment.Equipment.from_save(save())
    assert eq.exosuit.ids == ["PROTECT", "UP_JET1#50161"]
    assert [(t.title, t.active) for t in eq.multitools] == [
        ("Quantum Kay Needler (class A, in your hand)", True), ("Shitttool (class B)", False)]
    assert [c.name() for c in eq.exocraft] == ["Roamer (summoned first)", "Minotaur"]
    assert eq.freighter.ids == ["F_HYPERDRIVE"]
    assert eq.item_ids() == ["PROTECT", "UP_JET1#50161", "UP_LASER1#53433", "TERRAINEDITOR", "LASER",
                             "VEHICLE_ENGINE", "UP_EXGUN1#59766", "MECH_ENGINE", "F_HYPERDRIVE"]
    empty = equipment.Equipment.from_save({})
    assert empty.item_ids() == [] and empty.multitools == [] and empty.exocraft == []


class Texts:
    def item(self, item_id, text=None):
        return {"text": item_id, "icon": "x.png"}

    def category(self, item_id):
        return "Upgrade" if item_id.startswith("UP_") else None

    def modifiers(self, item_id):
        return ["Mining Speed +5-10 %", "Heat Dispersion +5-15 %"] if item_id.startswith("UP_LASER1") else []

    def label(self, key):
        return "Roamer (Rover)" if key == "VEHICLE_BUGGY_TITLE_L" else None


def test_the_equipment_tab_has_sub_tabs_with_what_each_part_does():
    """Sub-tabs Exosuit / Multi-tools / Exocraft / Freighter with counts; each part has icon, category, charge
    and what it does (the stat ranges); exocraft are named in the game's languages; a note explains ranges."""
    out = equipment.equipment_sections(equipment.Equipment.from_save(save()), Texts())
    tabs = out[0]["tabs"]
    assert [(t["label"], t["badge"]) for t in tabs] == [("Exosuit", 2), ("Multi-tools", 2), ("Exocraft", 2),
                                                        ("Freighter", 1)]
    exosuit = tabs[0]["sections"][0]
    assert exosuit["id"] == "exosuit-tech" and exosuit["title"] == "Exosuit technology (2)"
    assert exosuit["rows"][0] == [{"text": "PROTECT", "icon": "x.png"}, None, "80 / 100", None]
    needler = tabs[1]["sections"][0]
    assert needler["title"] == "Multi-tool: Quantum Kay Needler (class A, in your hand)"
    assert needler["rows"][0][1:] == ["Upgrade", None, "Mining Speed +5-10 %; Heat Dispersion +5-15 %"]
    assert needler["rows"][1][2] == "562 / 600"
    assert tabs[2]["sections"][0]["title"] == "Exocraft: Roamer (Rover) (summoned first)"
    assert "seed" in out[1]["text"]
    assert equipment.equipment_sections(None, Texts())[0]["type"] == "text"


def test_a_technology_part_without_a_name_is_not_read_out_as_its_id(tmp_path, monkeypatch):
    """A procedural corvette upgrade the language files have no key for is called "an unnamed upgrade module".

    Expected: the raw id is absent from the text and the stat ranges survive. It matters because the persona listed
    "CV_INV2#53297 (Cargo Slots +3)" to the player as the name of a ship part (chat test 2026-10-09)."""
    from test_connector import FakeCtx, create_plugin
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))

    class OneNamed:
        """Names the known part and gives the raw id back for the procedural one, as the game's texts do."""

        def name(self, item_id):
            return "Photon Cannon" if item_id == "SHIPGUN1" else item_id

    monkeypatch.setattr(type(plugin.companion), "_english_modifiers",
                        lambda self, item_id, texts: ["Cargo Slots +3"] if item_id == "CV_INV2#53297" else [])
    text = plugin.companion._technology_text([{"id": "SHIPGUN1"}, {"id": "CV_INV2#53297"}], OneNamed())
    assert "CV_INV2" not in text
    assert text == "Photon Cannon; an unnamed upgrade module (Cargo Slots +3)"

