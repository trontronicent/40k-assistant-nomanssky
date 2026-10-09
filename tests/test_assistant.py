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


def lookups(names=NAMES, name_of=None, **callbacks):
    """The ItemLookups of these tests: display names from `names` (or `name_of`), the callbacks given."""
    return assistant.ItemLookups(name_of or (lambda i: names[i][0]), lambda i: names[i], names, **callbacks)


def build(question, planets=None):
    return assistant.build_context(question, snapshot(), lookups(name_of=lambda i: f"{NAMES[i][0]} ({NAMES[i][1]})",
                                                                 planets_offering=planets), ["STATUS"], ["Timers: none"])


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
    nothing = assistant.ItemLookups(str, list, {})
    assert assistant.build_context("x", None, nothing, [], []) == "No save has been read yet, so there is no game data."


def test_a_question_naming_a_place_gets_that_inventorys_contents():
    """Seen in the chat of 2026-10-05: "what is in my ship inventory?" got only stack counts. Now a place in the
    question lists its contents - "ship" the one you fly, "storage container 7" only that container - and the odd
    corrupt id in a save is left out."""
    snap = snapshot()
    snap["ships"].append({"name": "(unnamed)", "class": "Hauler", "primary": False, "inventory": [["\ufffd\ufffd2#00", 1, 1]]})
    ids = assistant.ItemLookups(lambda i: NAMES.get(i, [i])[0], lambda i: NAMES.get(i, [i]), NAMES)
    text = assistant.build_context("What is in my ship inventory?", snap, ids, [], [])
    assert "Contents of Starship 'Bang' (primary) (1 stacks):" in text and "- Ferrite Dust [LAND1]: 300" in text
    assert "unnamed Hauler" not in text and "\ufffd" not in text
    container = assistant.build_context("show storage container 7", snapshot(), lookups(), [], [])
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
                                   lookups(names, item_notes=lambda i: "Sell at: Scientific economies." if i.startswith("TRA_") else None),
                                   [], [])
    assert "- Self-Repairing Heridium [TRA_ALLOY2]: 11 in total - Exosuit: 11" in text
    assert "  Sell at: Scientific economies." in text and "SCRAP_GOODS" not in text.split("Inventories:")[0]


def test_trade_goods_are_grouped_by_kind_in_the_place_asked_most_valuable_first():
    """Seen 2026-10-05: "what kind of trade goods do I have the most aboard my active ship?" got the largest
    single stack. Goods are now summed per kind (category) over the places asked - here only the ship, not the
    freighter - and ranked by base value x amount; unknown values count 0, other items are ignored."""
    from nms_connector import assistant
    snap = {"exosuit": [], "exosuit_cargo": [], "storage": [],
            "ships": [{"name": "Raptor", "primary": True, "inventory": [["TRA_TECH4", 78, 100], ["TRA_TECH1", 32, 100],
                                                                         ["TRA_MINERALS3", 66, 100], ["FUEL1", 9, 9]]}],
            "freighter": {"name": None, "inventory": [["TRA_TECH1", 60, 100]]}}
    values = {"TRA_TECH4": 30000, "TRA_TECH1": 1000, "TRA_MINERALS3": 15000}.get
    ship = [p for p, _ in assistant.places(snap) if p.startswith("Starship")]
    kinds = assistant.trade_kinds(snap, ship, values)
    assert [(k["category"], k["units"], k["value"]) for k in kinds] == [("Tech", 110, 2_372_000), ("Mineral", 66, 990_000)]
    assert kinds[0]["goods"] == [("TRA_TECH4", 78), ("TRA_TECH1", 32)]
    everywhere = assistant.trade_kinds(snap, None, values)
    assert everywhere[0]["units"] == 170
    assert assistant.trade_kinds(snap, ship, lambda i: None)[0]["value"] == 0


MERGE_NAMES = dict(NAMES, TRA_ALLOY2=["Self-Repairing Heridium", "Sich selbst reparierendes Heridium"],
                   CONTAINER0=["Storage Container", "Lagerbehälter"])
MERGE_QUESTIONS = [
    "List me all items that are present in different storage containers and where it could be comined into a single stack",
    "Liste mir alle Stacks aus Storage Containern die sich zusammenführen liessen",
    "Liste mir alle Items aus Containern die zusammengeführt werden können",
]


def build_merge(question):
    """The context for `question` with the items that tripped the German chat of 2026-10-08 (session cdee88f2)."""
    snap = snapshot()
    snap["exosuit"].append(["TRA_ALLOY2", 11, 9999])
    return assistant.build_context(question, snap, lookups(MERGE_NAMES), ["STATUS"], [])


def test_a_non_merge_place_question_lists_the_contents_in_english_and_german():
    """'What is in my containers?' (English, German with the dative plural 'Containern') names no item, so the
    persona gets the contents of both storage containers. Before: 'sich' matched 'Sich selbst reparierendes
    Heridium' and 'Containern' the Storage Container items, and an item match replaced the container contents."""
    for question in ("What is in my storage containers?", "Was liegt in meinen Containern?",
                     "Zeig mir den Inhalt der Lagerbehälter, die sich auf dem Frachter befinden"):
        text = build_merge(question)
        assert "Contents of Storage Container 0 (2 stacks):" in text, question
        assert "Contents of Storage Container 7 (2 stacks):" in text, question
        assert "Items the question names" not in text and "Stacks that can be merged" not in text, question


def test_merge_questions_get_the_stacks_to_merge_not_the_contents():
    """English and German merge wordings (incl. the two of the chat of 2026-10-08) get the 'Stacks that can be
    merged' section: copper is in both containers (581 + 119 fits in one stack), nothing else is listed, and the
    raw contents, an item section and trade goods are not added - the plugin did the grouping the model got wrong."""
    for question in MERGE_QUESTIONS + ["Welche Items liegen in mehr als einem Lagerbehälter?",
                                       "Which items are in several containers and could be merged?"]:
        text = build_merge(question)
        assert "Stacks that can be merged" in text, question
        assert "- Copper [YELLOW2]: 700 in 2 stacks, stack limit 9,999 -> 1 stack after merging - "                "Storage Container 0: 581; Storage Container 7: 119" in text, question
        assert "Contents of" not in text and "Items the question names" not in text, question
        assert "[EX_YELLOW]" not in text and "[CAVE1]" not in text, question     # one stack in the asked inventories


def test_merge_without_a_named_place_looks_across_all_inventories():
    """'Which items have several stacks I could merge?' names no place: cobalt in the exosuit and in container 7
    (1,875 + 3,052) is a candidate too, with each place and its amount."""
    text = build_merge("Which items have several stacks that I could merge?")
    assert "- Cobalt [CAVE1]: 4,927 in 2 stacks" in text and "Exosuit: 1,875; Storage Container 7: 3,052" in text


def test_merging_respects_the_stack_limit_and_names_lookalikes():
    """Two full stacks cannot merge (nothing saved: left out); 30 + 5 with limit 40 -> 1 stack. Two ids with the
    same name (the two Geode items) are each flagged as a different item than the other, never added together."""
    from nms_connector import merging
    places = [("A", [["FULL", 9999, 9999], ["PART", 30, 40], ["GEODE_LAND", 40, 100], ["GEODE_CAVE", 30, 100]]),
              ("B", [["FULL", 9999, 9999], ["PART", 5, 40], ["GEODE_LAND", 30, 100], ["GEODE_CAVE", 30, 100]])]
    text = "\n".join(merging.merge_lines(places, lambda i: "Geode" if i.startswith("GEODE") else i))
    assert "[FULL]" not in text and "- PART [PART]: 35 in 2 stacks, stack limit 40 -> 1 stack after merging" in text
    assert "(not the same item as GEODE_CAVE: same name, other id)" in text
    assert "(not the same item as GEODE_LAND: same name, other id)" in text


def test_merging_nothing_to_merge_says_so():
    """When no item has stacks that would fit together the section says 'none', so the model does not invent any."""
    from nms_connector import merging
    text = "\n".join(merging.merge_lines([("A", [["X", 9999, 9999]]), ("B", [["X", 9999, 9999]])], str))
    assert "- none:" in text


def test_is_merge_question_tells_merging_from_crafting():
    """Merge wordings match; plain inventory and crafting questions do not (they must keep their own sections)."""
    from nms_connector.merging import is_merge_question
    for q in ("zusammengeführt werden können", "Stacks zusammenlegen", "doppelte Items", "merge my stacks",
              "items in several containers", "one single stack please"):
        assert is_merge_question(q), q
    for q in ("Wie viel Kobalt habe ich?", "what can I craft with copper?", "Was ist in Container 7?"):
        assert not is_merge_question(q), q


def test_a_named_place_and_a_named_item_both_get_their_section():
    """'Copper in storage container 0' names an item and a place: the item section (totals over all inventories)
    and the container's contents are both given - the item match no longer hides the place."""
    text = build("how much copper is in storage container 0?")
    assert "- Copper (Kupfer) [YELLOW2]: 700 in total" in text
    assert "Contents of Storage Container 0 (2 stacks):" in text and "Contents of Storage Container 7" not in text


def test_german_place_inflections_name_the_place():
    """'Containern', 'Behältern' and 'Lagern' (dative plurals) name the storage containers like 'containers' does."""
    for question in ("was liegt in meinen Containern", "was liegt in meinen Behältern", "was ist in meinen Lagern"):
        assert assistant.places_asked(question, snapshot()) == ["Storage Container 0", "Storage Container 7"], question


def test_storage_containers_do_not_include_the_other_storage():
    """'Storage Containern' / 'Lagerbehälter' name the numbered containers only; 'storage' or 'Lager' alone keep
    meaning containers and the other storage. Seen 2026-10-08: the merge list held CookingIngredients and ChestMagic."""
    snap = snapshot()
    snap["storage"].append({"number": None, "key": "CookingIngredientsInventory", "rows": [["YELLOW2", 5, 9999]]})
    assert assistant.places_asked("merge items in storage containers", snap) == ["Storage Container 0", "Storage Container 7"]
    assert assistant.places_asked("Was liegt in den Lagerbehältern", snap) == ["Storage Container 0", "Storage Container 7"]
    assert "Other storage (CookingIngredients)" in assistant.places_asked("what is in my storage", snap)


def test_a_named_item_that_does_not_fit_in_one_stack_is_explained():
    """'Can I merge my cobalt into one stack?' - cobalt (1,875 + 3,052 = 4,927) fits, but with a limit of 3,000 it
    would not: the line says there is no saving instead of the persona answering about another cobalt item."""
    from nms_connector import merging
    places = [("Exosuit", [["CAVE1", 1875, 3000]]), ("Storage Container 7", [["CAVE1", 3052, 3000]])]
    text = "\n".join(merging.merge_lines(places, lambda i: "Cobalt", {"CAVE1"}))
    assert "- Cobalt [CAVE1]: 4,927 in 2 stacks, stack limit 3,000 -> 2 stacks after merging" in text
    assert "no saving: the amounts do not fit into fewer stacks" in text
    assert "- none:" in "\n".join(merging.merge_lines(places, lambda i: "Cobalt"))     # not named: left out


def test_the_merge_list_is_capped():
    """A vague question over every inventory lists at most MAX_LINES items and says how many more there are."""
    from nms_connector import merging
    rows = [[f"I{n}", 1, 10] for n in range(40)]
    lines = merging.merge_lines([("A", rows), ("B", rows)], str)
    items = [line for line in lines if line.startswith("- I")]
    assert len(items) == merging.MAX_LINES and lines[-1].startswith("- ... and 15 more items")


def test_a_misspelt_item_name_is_read_as_the_item_and_says_so():
    """'wieviel Aroniun hab ich' (one letter off) is read as Aronium: the data names the item, its total and place,
    and a note says how the word was read. A word that is no item word and not close to one ('Einhornstaub') still
    gives no item, and a real item word ('Copper') is never 'corrected'. Before: the persona said 0 for the typo."""
    names = dict(NAMES, ALLOY1=["Aronium", "Aronium"])
    snap = snapshot()
    snap["storage"][1]["rows"].append(["ALLOY1", 2, 20])
    look = lookups(names)
    text = assistant.build_context("wieviel Aroniun hab ich?", snap, look, ["STATUS"], [])
    assert '(The question word "aroniun" was read as "Aronium" [ALLOY1].)' in text
    assert "- Aronium [ALLOY1]: 2 in total - Storage Container 7: 2" in text
    assert assistant.near_miss_items("Wie viel Einhornstaub habe ich?", names) == []
    assert assistant.near_miss_items("how much Copper do I have", names) == []
    assert assistant.near_miss_items("Aroni", names) == []                       # too short to guess


def test_a_named_item_with_one_stack_says_there_is_nothing_to_merge():
    """'Kann ich mein Aronium zusammenlegen?' (and with the typo 'Aroniun'): one stack of 2 in container 7 -
    the section says 'only one stack: nothing to merge' instead of leaving the model to say the data has no answer."""
    names = dict(NAMES, ALLOY1=["Aronium", "Aronium"])
    snap = snapshot()
    snap["storage"][1]["rows"].append(["ALLOY1", 2, 20])
    for question in ("Kann ich mein Aronium zusammenlegen?", "Kann ich mein Aroniun zusammenlegen?"):
        text = assistant.build_context(question, snap, lookups(names), ["STATUS"], [])
        assert "- Aronium [ALLOY1]: 2 in 1 stack, stack limit 20 - Storage Container 7: 2 (only one stack: nothing to merge)" in text, question


def test_a_word_with_another_first_letter_is_no_typo():
    """Chat test 2026-10-09: 'how much Dilithium do I have?' (no such item in the game) was read as a misspelt
    'Lithium' (ratio 0.875). A typo keeps the first letter, so an unknown name stays unknown and the persona can say
    the game has no such item instead of reporting a different one."""
    names = dict(NAMES, WATERWORLD1=["Lithium", "Lithium"])
    assert assistant.near_miss_items("how much Dilithium do I have?", names) == []
    assert assistant.near_miss_items("how much Lithum do I have?", names) == [("lithum", "WATERWORLD1")]


def test_misspellings_are_read_by_sound():
    """'Paraphinium', 'Paraphine' and 'Paraphenium' (chat of 2026-10-09, ph for f) all mean Paraffinium: words are
    compared folded (ph -> f, doubled letters single, y -> i, umlauts plain), then by closeness, then as a stem one
    letter short. An item word that exists is never corrected, and a word close to nothing stays unmatched."""
    names = dict(NAMES, LUSH1=["Paraffinium", "Paraffinium"], PLANT_LUSH=["Star Bulb", "Sternenknolle"])
    for question, word in (("Wie viel Paraphinium habe ich?", "paraphinium"), ("wie stelle ich Paraphine her?", "paraphine"),
                           ("how do I create Paraphenium?", "paraphenium")):
        assert assistant.near_miss_items(question, names) == [(word, "LUSH1")], question
    assert assistant.near_miss_items("how much Paraffinium", names) == []
    assert assistant.near_miss_items("Wie viel Einhornstaub habe ich?", names) == []
    assert assistant.fold("Paraphinium") == assistant.fold("Paraffinium") == "parafinium"


def test_a_long_message_without_an_item_cue_gets_no_near_miss_item():
    """Chat test 2026-10-09: 'write me a python function that reverses a string' was read as Piston, Funktion and
    Stirring Void Egg (three near matches), and the persona listed them with '0 - not in any inventory'. A message of
    more than 6 words without an amount/recipe/place cue is no item question; short ones and ones with a cue keep
    the typo reading."""
    names = dict(NAMES, TRA_COMPONENT2=["Non-Stick Piston", "Antihaftkolben"], NEW_PERK=["Feature", "Funktion"],
                 LUSH1=["Paraffinium", "Paraffinium"])
    assert assistant.near_miss_items("write me a python function that reverses a string", names) == []
    assert assistant.near_miss_items("how much Paraphinium do I have?", names) == [("paraphinium", "LUSH1")]
    assert assistant.near_miss_items("I would like to know about the Paraphinium situation", names) == []
    assert assistant.near_miss_items("I would like to know where to find Paraphinium", names) == [("paraphinium", "LUSH1")]


def test_a_currency_is_not_reported_as_an_item_the_player_lacks():
    """'how many units do I have?' printed 'UNITS [UNITS]: 0 - not in any of your inventories' beside the real balance
    of the status line. Currencies are in the player state, so the item section leaves them out."""
    names = dict(NAMES, UNITS=["UNITS", "UNITS"])
    text = assistant.build_context("how many units do I have?", snapshot(), lookups(names), ["Units 38,221,481"], [])
    assert "[UNITS]" not in text and "Units 38,221,481" in text


def test_a_french_or_italian_elision_does_not_hide_the_item_word():
    """'l'ammoniac' and 'dell'ammoniaca' are one token for the word regex; the elision is cut off so the item is
    found. English contractions ('don't', 'it's') keep their words."""
    assert assistant._words("Comment fabriquer de l'ammoniac ?") == ["comment", "fabriquer", "de", "ammoniac"]
    assert assistant._words("la ricetta dell'ammoniaca") == ["la", "ricetta", "ammoniaca"]
    assert assistant._words("don't tell me it's gold") == ["don't", "tell", "me", "it's", "gold"]


def test_an_ordinal_of_a_follow_up_names_no_item():
    """'and the last one?' matched the poster 'Built to Last' and answered with its recipe (chat test 2026-10-09).
    Ordinals are stopwords: they never name an item by themselves."""
    names = {"POSTER": ["Built to Last Poster", "Poster"], "SKIN1": ["Second Skin", "Zweite Haut"]}
    for question in ("and the last one?", "what about the second one?", "und das dritte, zweite, letzte?"):
        assert assistant.match_items(question, names) == [], question
    assert assistant.match_items("recipe for the Built to Last Poster", names) == ["POSTER"]


def test_unowned_items_are_listed_only_for_ownership_questions():
    """'what is the difference between a Portable Refiner and a Large Refiner?' began with 'Portable Refiner: 0. Large
    Refiner: 0.' (chat test 2026-10-09). A '0 - not in any inventory' line needs an ownership cue (how much, do I
    have ...); 'how much Gold do I have' still says 0."""
    names = dict(NAMES, REFINER1=["Portable Refiner", "Tragbare Raffinerie"])
    text = assistant.build_context("what is a Portable Refiner for?", snapshot(), lookups(names), ["S"], [])
    assert "Portable Refiner" not in text
    text = assistant.build_context("how much Gold do I have?", snapshot(), lookups(names), ["S"], [])
    assert "Gold [GOLD]: 0" in text


def test_most_abundant_questions_get_the_largest_stacks_and_the_item_count_is_stated():
    """'what is my most abundant resource?' was answered with the Units balance - the block had no ranking. It now
    holds the largest stacks, and the inventory line says how many different items the player owns ('how many
    different items do I own?' was 'data not available')."""
    text = assistant.build_context("what is my most abundant resource?", snapshot(), lookups(), ["S"], [])
    assert "Your largest stacks in all" in text and text.index("Cobalt") < text.index("Copper")
    assert "different items in total." in text
    assert "Your largest stacks" not in assistant.build_context("how is the weather", snapshot(), lookups(), ["S"], [])
