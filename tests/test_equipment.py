"""Tests for the Equipment tab: exosuit technology, multi-tools and freighter technology from the save."""

from nms_connector import equipment


def tech(tid, amount=-1, maximum=100):
    return {"Type": {"InventoryType": "Technology"}, "Id": f"^{tid}", "Amount": amount, "MaxAmount": maximum}


def save():
    """Kay's equipment on 2026-10-04 (trimmed): exosuit parts, two used multi-tools and three unused entries
    (no model), the active one at index 2 ("ActiveMultioolIndex", spelled so in the save), a freighter drive."""
    unused = {"Name": "", "Resource": {"Filename": ""}, "Store": {"Class": {"InventoryClass": "C"}}}
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
        "FreighterInventory_TechOnly": {"Slots": [tech("F_HYPERDRIVE", 96, 120)]}}}}


def test_equipment_is_read_with_the_multitool_in_your_hand_first():
    """Only technology slots count (not the fuel in the general inventory); unused multi-tool entries are
    skipped; the active one comes first and is marked."""
    eq = equipment.equipment_from_save(save())
    assert [t["id"] for t in eq["exosuit"]] == ["PROTECT", "UP_JET1#50161"]
    assert [(t["name"], t["class"], t["active"]) for t in eq["multitools"]] == [
        ("Quantum Kay Needler", "A", True), ("Shitttool", "B", False)]
    assert eq["freighter"][0]["id"] == "F_HYPERDRIVE"
    assert equipment.item_ids(eq) == ["PROTECT", "UP_JET1#50161", "F_HYPERDRIVE", "UP_LASER1#53433", "TERRAINEDITOR", "LASER"]
    assert equipment.equipment_from_save({}) == {"exosuit": [], "multitools": [], "freighter": []}


class Texts:
    def item(self, item_id, text=None):
        return {"text": item_id, "icon": "x.png"}

    def category(self, item_id):
        return "Upgrade" if item_id.startswith("UP_") else None


def test_the_equipment_tab_lists_each_part_with_icon_category_and_charge():
    """One table for the exosuit, one per multi-tool (title says which is in your hand), one for the freighter;
    parts without charge show none."""
    out = equipment.equipment_sections(equipment.equipment_from_save(save()), Texts())
    titles = [s.get("title") for s in out]
    assert titles[:4] == ["Exosuit technology (2)", "Multi-tool: Quantum Kay Needler (class A, in your hand)",
                          "Multi-tool: Shitttool (class B)", "Freighter technology (1)"]
    assert out[0]["rows"][0] == [{"text": "PROTECT", "icon": "x.png"}, None, "80 / 100"]
    assert out[1]["rows"][0][1:] == ["Upgrade", None] and out[1]["rows"][1][2] == "562 / 600"
    assert equipment.equipment_sections(None, Texts())[0]["type"] == "text"
