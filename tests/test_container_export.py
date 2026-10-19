"""Copying storage container contents (one container or all of them, TOON or JSON) - the container
counterpart of the ship export."""
import asyncio
import json

import pytest

from nms_connector import container_export, toon

STORAGE = [{"number": 0, "key": "Chest1Inventory", "name": "BLD_STORAGE_NAME",
            "rows": [["YELLOW2", 581, 9999], ["TRA_ALLOY1", 3, 10]]},
           {"number": 1, "key": "Chest2Inventory", "name": None, "rows": []},
           {"number": 7, "key": "Chest8Inventory", "name": "Metals", "rows": [["YELLOW2", 119, 9999]]}]
ITEMS = {"YELLOW2": {"en": "Copper", "value": 41}, "TRA_ALLOY1": {"en": "Aronium", "value": 1000}}


class FakeTexts:
    def name(self, item_id):
        return (ITEMS.get(item_id) or {}).get("en")


def test_one_container_carries_every_stack_with_its_base_value():
    """A container's export names it as the page does (no BLD_* default name), and lists every stack with its
    amount, limit, unit and stack value, plus the container's total - the facts its table shows."""
    data = container_export.container_data(STORAGE[0], FakeTexts(), ITEMS.get)
    assert data["container"] == "Storage Container 0" and data["key"] == "Chest1Inventory" and data["stacks"] == 2
    assert data["items"][0] == {"id": "YELLOW2", "name": "Copper", "amount": 581, "max": 9999,
                                "value_each": 41, "value_stack": 23821}
    assert data["value_total"] == 23821 + 3000
    assert container_export.label(STORAGE[2]) == "Storage Container 7: Metals"


def test_an_item_without_a_value_has_none_rather_than_zero():
    """An item the game gives no base value keeps None (null), never a 0 that reads as worthless."""
    chest = {"number": 2, "key": "Chest3Inventory", "name": None, "rows": [["UP_HYP4", 1, 1]]}
    data = container_export.container_data(chest, FakeTexts(), ITEMS.get)
    assert data["items"][0]["name"] == "UP_HYP4" and data["items"][0]["value_each"] is None
    assert data["value_total"] is None


def test_all_containers_skip_the_empty_ones_and_name_them():
    """'All' exports every container that holds something, in the game's order, and lists the empty
    numbers instead of writing empty item lists."""
    data = container_export.all_data(STORAGE, FakeTexts(), ITEMS.get)
    assert [c["container"] for c in data["containers"]] == ["Storage Container 0", "Storage Container 7: Metals"]
    assert data["empty"] == [1]


def test_the_items_are_written_as_one_toon_table_per_container():
    """Every item row has the same keys, so TOON writes each container's items as one header plus bare rows,
    which is what makes it smaller than JSON."""
    data = container_export.container_data(STORAGE[0], FakeTexts(), ITEMS.get)
    text = toon.encode(data)
    assert "items[2]{id,name,amount,max,value_each,value_stack}:" in text
    assert len(text) < len(json.dumps(data, separators=(",", ":")))


def test_the_overview_offers_the_menu_on_every_full_container():
    """The Storage overview has one row per full container, keyed by its save key, with the four copy entries
    and the TOON copy on a left click (an app before 3.18.0 drops the unknown row_menu, the click still works)."""
    table = container_export.overview_section(STORAGE, ITEMS.get)
    assert table["row_keys"] == ["Chest1Inventory", "Chest8Inventory"]
    assert table["rows"][0] == ["Storage Container 0", 2, 584, 23821 + 3000]
    assert [i["id"] for i in table["row_menu"]] == list(container_export.EXPORT_ACTIONS)
    assert all(i["label"] and i["description"] for i in table["row_menu"])
    assert table["row_action"] == container_export.EXPORT_TOON and "Right-click" in table["row_hint"]
    assert container_export.overview_section([STORAGE[1]], ITEMS.get) is None


def _plugin(tmp_path, monkeypatch):
    from nms_connector import create_plugin
    from test_connector import FakeCtx
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.snapshot = {"storage": STORAGE}
    return plugin


def test_the_action_checks_its_key_and_answers_with_the_text(tmp_path, monkeypatch):
    """The key is untrusted: only a container of the newest save counts. A good one answers `copy` with the
    text and keeps it for the page (a browser without a secure context refuses the clipboard)."""
    plugin = _plugin(tmp_path, monkeypatch)
    for bad in ({}, {"key": "nonsense"}, {"key": "Chest9Inventory"}):
        assert plugin._export_container(container_export.EXPORT_TOON, bad)["ok"] is False
    assert plugin.container_export is None

    answer = plugin._export_container(container_export.EXPORT_JSON, {"key": " Chest8Inventory "})
    assert answer["ok"] and json.loads(answer["copy"])["container"] == "Storage Container 7: Metals"
    assert answer["focus"] == container_export.EXPORT_ID
    assert plugin.container_export["format"] == "JSON" and plugin.container_export["text"] == answer["copy"]
    section = container_export.export_section(plugin.container_export)[0]
    assert section["id"] == container_export.EXPORT_ID and section["text"] == answer["copy"]


def test_copy_all_needs_no_key_and_refuses_an_empty_storage(tmp_path, monkeypatch):
    """'All containers' ignores the row it was opened on, and says so plainly when nothing is stored."""
    plugin = _plugin(tmp_path, monkeypatch)
    answer = plugin._export_container(container_export.EXPORT_ALL_TOON, {"key": "Chest1Inventory"})
    assert answer["ok"] and "containers[2]:" in answer["copy"] and "(3 stacks)" in answer["message"]
    plugin.snapshot = {"storage": [STORAGE[1]]}
    assert plugin._export_container(container_export.EXPORT_ALL_JSON, {})["ok"] is False


@pytest.mark.parametrize("action", container_export.EXPORT_ACTIONS)
def test_every_container_export_action_is_registered(action, tmp_path, monkeypatch):
    """Each menu entry is an action the connector answers - through `action()`, the way both hosts call it."""
    plugin = _plugin(tmp_path, monkeypatch)
    answer = asyncio.run(plugin.action(action, {"key": "Chest1Inventory"}))
    assert answer["ok"] and answer["copy"]
