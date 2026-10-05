"""Tests for the chat data of the plugin persona: item matching, totals per inventory, the context text."""

from nms_connector import assistant

NAMES = {"YELLOW2": ["Copper", "Kupfer"], "EX_YELLOW": ["Activated Copper", "Aktiviertes Kupfer"],
         "CATALYST1": ["Sodium", "Natrium"], "CAVE1": ["Cobalt", "Kobalt"], "LAND1": ["Ferrite Dust", "Ferritstaub"],
         "TECH_COMP": ["Wiring Loom", "Kabelbaum"], "GOLD": ["Gold", "Gold"]}


def snapshot():
    """Kay's inventories on 2026-10-05 (trimmed): copper in two storage containers, sodium in the exosuit."""
    return {"exosuit": [["CATALYST1", 23, 250], ["CAVE1", 1875, 9999]], "exosuit_cargo": [],
            "ships": [{"name": "Bang", "primary": True, "inventory": [["LAND1", 300, 500]]}],
            "freighter": {"name": None, "inventory": []},
            "storage": [{"number": 0, "key": "Chest1Inventory", "name": None, "rows": [["YELLOW2", 581, 9999], ["EX_YELLOW", 103, 9999]]},
                        {"number": 7, "key": "Chest8Inventory", "name": "BLD_STORAGE", "rows": [["YELLOW2", 119, 9999], ["CAVE1", 3052, 9999]]}],
            "saved_at": "2026-10-04T22:44:00+00:00"}


def test_items_are_matched_by_english_or_game_language_name_whole_or_by_word():
    """'copper' finds Copper and Activated Copper (a word of its name); the German 'Natrium' finds Sodium; plurals
    and question words do not get in the way; short words never match on their own."""
    owned = {k: v for k, v in NAMES.items() if k in ("YELLOW2", "EX_YELLOW", "CATALYST1", "CAVE1", "LAND1")}
    assert assistant.match_items("How much Copper do I have?", owned) == ["YELLOW2", "EX_YELLOW"]
    assert assistant.match_items("wie viel Natrium habe ich?", owned) == ["CATALYST1"]
    assert assistant.match_items("where are my coppers", owned) == ["YELLOW2", "EX_YELLOW"]
    assert assistant.match_items("how much ferrite dust", owned)[0] == "LAND1"
    assert assistant.match_items("how much do I have", owned) == []


def test_holdings_add_up_every_inventory_with_its_place():
    """Totals across exosuit, ships, freighter and storage containers, each place named as in the game; a
    container named by the game (BLD_...) keeps its number only."""
    have = assistant.holdings(snapshot())
    assert have["YELLOW2"] == {"total": 700, "places": [("Storage Container 0", 581), ("Storage Container 7", 119)]}
    assert have["CAVE1"]["total"] == 4927 and have["LAND1"]["places"] == [("Starship 'Bang' (primary)", 300)]


def build(question, planets=None):
    return assistant.build_context(question, snapshot(), lambda i: f"{NAMES[i][0]} ({NAMES[i][1]})",
                                   lambda i: NAMES[i], NAMES, ["STATUS"], ["Timers: none"], planets)


def test_the_context_answers_how_much_copper_with_total_and_places():
    """The motivating question: the text gives the total and the amount per inventory, plus related items and
    where the item was seen on planets; status and other lines are always there."""
    text = build("How much Copper do I have?", lambda i: ["Ciferd in Kayanis Majoris VIII (same region)"])
    assert "- Copper (Kupfer) [YELLOW2]: 700 in total - Storage Container 0: 581; Storage Container 7: 119" in text
    assert "Activated Copper (Aktiviertes Kupfer) [EX_YELLOW]: 103 in total" in text
    assert "found on: Ciferd in Kayanis Majoris VIII" in text
    assert text.startswith("STATUS") and "Timers: none" in text and "Inventories: Exosuit (2 stacks)" in text


def test_items_you_do_not_have_are_reported_as_zero_and_inventory_questions_list_the_largest_stacks():
    """A named item that is in no inventory is said to be 0 (not left out, which would invite guessing); an
    inventory question without a named item lists the largest stacks in all; no save means no data."""
    assert "- Wiring Loom (Kabelbaum) [TECH_COMP]: 0 - not in any of your inventories" in build("do I have a wiring loom?")
    top = build("what is in my inventory")
    assert "Your largest stacks in all" in top and top.index("Cobalt") < top.index("Copper (Kupfer) [YELLOW2]")
    assert assistant.build_context("x", None, str, list, {}, [], []) == "No save has been read yet, so there is no game data."


def test_a_question_naming_a_place_gets_that_inventorys_contents():
    """Seen in the chat of 2026-10-05: "what is in my ship inventory?" got only stack counts. Now a place in the
    question lists its contents - "ship" the one you fly, "storage container 7" only that container - and the odd
    corrupt id in a save is left out."""
    snap = snapshot()
    snap["ships"].append({"name": "(unnamed)", "class": "Hauler", "primary": False, "inventory": [["\ufffd\ufffd2#00", 1, 1]]})
    text = assistant.build_context("What is in my ship inventory?", snap, lambda i: NAMES.get(i, [i])[0],
                                   lambda i: NAMES.get(i, [i]), NAMES, [], [])
    assert "Contents of Starship 'Bang' (primary) (1 stacks):" in text and "- Ferrite Dust [LAND1]: 300" in text
    assert "unnamed Hauler" not in text and "\ufffd" not in text
    container = assistant.build_context("show storage container 7", snapshot(), lambda i: NAMES[i][0],
                                        lambda i: NAMES[i], NAMES, [], [])
    assert "Contents of Storage Container 7" in container and "Contents of Storage Container 0" not in container
    assert assistant.places_asked("all my ships", snap)[0] == "Starship 'Bang' (primary)"


def test_trade_goods_questions_list_every_trade_good_with_where_it_sells():
    """"What trade goods do I have?" matched only "Suspicious Packet (Goods)" by the word "goods" and missed
    Self-Repairing Heridium and Nanotube Crate: now every trade good (TRA_*) is listed with item_notes - where it
    sells - and a goods item that is no trade good is not."""
    snap = snapshot()
    snap["exosuit"] += [["TRA_ALLOY2", 11, 50], ["SCRAP_GOODS", 2, 10]]
    names = dict(NAMES, TRA_ALLOY2=["Self-Repairing Heridium", "Heridium"], SCRAP_GOODS=["Suspicious Packet (Goods)", "Paket"])
    text = assistant.build_context("What trade goods do I have and where should I sell them?", snap,
                                   lambda i: names[i][0], lambda i: names[i], names, [], [],
                                   item_notes=lambda i: "Sell at: Scientific economies." if i.startswith("TRA_") else None)
    assert "- Self-Repairing Heridium [TRA_ALLOY2]: 11 in total - Exosuit: 11" in text
    assert "  Sell at: Scientific economies." in text and "SCRAP_GOODS" not in text.split("Inventories:")[0]
