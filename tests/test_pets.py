"""Companions, eggs and creature-battle abilities (nms_connector/pets.py), with pets shaped like the real save's.

The move table is faked with the project's `build_table`; the pet records copy the real save (2026-10-10): the
`^COW` pet "Unzy Bunzy Bowa" with trust 0.75, three signed traits, 22 victories, five template moves.
"""
import pytest

from nms_connector import mbin, pets
from test_gamedata import build_table

NOW = 1_791_600_000.0

LAYOUT = {"id": (0x10, "f32"), "text": (0x34, "f32"), "kind": (0xB4, "f32")}
MOVES = [
    {"id": "ATTACK_DUST", "text": "Direct damage of one affinity", "kind": "ATTACK"},
    {"id": "SELF_HOT", "text": "Heal over time on self", "kind": "HEAL"},
    {"id": "DEBUFF_DEF", "text": "Lowers the target defence", "kind": "DEBUFF"},
]


def move_table(records=None) -> bytes:
    return build_table(records or MOVES, LAYOUT, 0x138)


def raw_pet(**over):
    """A pet record as the save stores it."""
    base = {
        "Scale": 0.656, "CreatureID": "^COW", "Descriptors": ["^_TAIL_THIN"],
        "CreatureSeed": [True, "0x320E447D6296A867"], "CreatureSecondarySeed": [True, "0x56427E9D16C14071"],
        "SpeciesSeed": "0x269DB40F01A2201D", "GenusSeed": "0xAA78C244162F491A",
        "UA": "0x20B70002925E80", "Biome": {"Biome": "Lush"}, "CreatureType": {"CreatureType": "Prey"},
        "BirthTime": 1_788_448_379, "LastEggTime": 1_791_140_239, "HasBeenSummoned": True,
        "CustomName": "Unzy Bunzy Bowa", "Trust": 0.7500000596046448,
        "Traits": [0.2489224672317505, -0.7318943738937378, -0.16034090518951416], "Moods": [0.0116, 0.0307],
        "PetBattlerCoreStatClassOverrides": [{"InventoryClass": "C"}] * 3,
        "PetBattlerTreatsEaten": [6, 0, 7], "PetBattlerTreatsAvailable": 2, "PetBattlerVictories": 22,
        "PetBattlerMoves": ["^ATTACK_DUST", "^AFF_SPEED_THEM", "^SELF_HOT", "^", "^DEBUFF_DEF"],
    }
    base.update(over)
    return base


def test_the_move_table_is_read_by_id_description_and_class():
    """parse_moves finds each record's template id (0x10), the game's own English description (0x34) and its
    class (0xB4) with the project's self-calibrating reader. Abilities are shown by these, so a wrong offset
    would put one move's description on another."""
    moves = pets.parse_moves(move_table())
    assert set(moves) == {"ATTACK_DUST", "SELF_HOT", "DEBUFF_DEF"}
    assert moves["SELF_HOT"] == pets.Move("SELF_HOT", "HEAL", "Heal over time on self")


def test_a_table_that_is_not_a_move_table_is_refused():
    """A table whose ids are not template-shaped (or that has none) raises MbinError instead of yielding
    nonsense moves - so a game update that moved a field costs the abilities, not the correctness."""
    junk = build_table([{"id": "not an id!", "text": "x", "kind": "y"}], LAYOUT, 0x138)
    with pytest.raises(mbin.MbinError):
        pets.parse_moves(junk)
    with pytest.raises(mbin.MbinError):
        pets.parse_moves(b"\x00" * 100)


def test_load_moves_without_an_installation_is_empty():
    """No game installed means no move table and no error: abilities then show their template ids only."""
    assert pets.load_moves(None) == {}


def test_harvest_words_come_from_the_games_language_keys():
    """PetBook reads UI_LABEL_HARVEST_<ID> and FOOD_<ID>_VEG/MEAT_NAME_L: a cow gives milk and steak, in
    English with the game language in brackets. The harvest is read from the game, not guessed."""
    english = {"UI_LABEL_HARVEST_COW": "Collect Milk", "FOOD_COW_VEG_NAME_L": "Fresh Milk",
               "FOOD_COW_MEAT_NAME_L": "Raw Steak", "UI_PB_AFFINITY_DUST_L": "Desert", "OTHER_KEY": "ignored"}
    local = {"UI_LABEL_HARVEST_COW": "Milch sammeln", "FOOD_COW_VEG_NAME_L": "Frische Milch",
             "FOOD_COW_MEAT_NAME_L": "Rohes Steak"}
    book = pets.PetBook.from_texts(english, local, "german")
    assert book.harvest("COW") == {"action": "Collect Milk (Milch sammeln)", "veg": "Fresh Milk (Frische Milch)",
                                   "meat": "Raw Steak (Rohes Steak)"}
    assert book.harvest("NOPE") == {} and book.affinities == {"DUST": "Desert"}
    assert pets.PetBook.from_texts(english, None, None).harvest("COW")["veg"] == "Fresh Milk"


def test_only_the_keys_companions_need_are_requested():
    """wanted_key accepts harvest, food, affinity and stat-header keys and nothing else, so the one pass over
    the language files keeps only what is needed (a predicate that matched everything would hold 84,000
    strings in RAM)."""
    assert all(pets.wanted_key(k) for k in ("UI_LABEL_HARVEST_COW", "FOOD_COW_VEG_NAME_L", "FOOD_COW_MEAT_NAME_L",
                                            "UI_PB_AFFINITY_HOT_L", "UI_PB_STAT_HEADER_SPEED"))
    assert not any(pets.wanted_key(k) for k in ("UI_LABEL_NO_HARVEST_COW", "FOOD_COW_NAME", "UI_PB_MOVE_COLD_ATTACK1",
                                                "CHAT_PET_ACTIVITY_1", ""))


def test_a_pet_is_reduced_to_the_fields_the_plugin_uses():
    """compact() turns a save record into a small JSON-safe dict: the name, the genus token without its caret,
    type, biome, trust, birth and egg times, the origin address, the battle record and the five moves with
    empty slots dropped. The snapshot holds 48 of these, so only what is shown is kept."""
    import json
    pet = pets.compact(raw_pet())
    assert (pet["name"], pet["id"], pet["type"], pet["biome"]) == ("Unzy Bunzy Bowa", "COW", "Prey", "Lush")
    assert pet["trust"] == 0.75 and pet["wins"] == 22 and pet["treats"] == [6, 0, 7] and pet["treats_free"] == 2
    assert pet["moves"] == ["ATTACK_DUST", "AFF_SPEED_THEM", "SELF_HOT", "DEBUFF_DEF"], "the empty '^' slot is dropped"
    assert pet["classes"] == ["C", "C", "C"] and pet["ua"] == 0x20B70002925E80
    assert pet["seeds"] == [0x320E447D6296A867, 0x56427E9D16C14071, 0x269DB40F01A2201D, 0xAA78C244162F491A]
    assert json.loads(json.dumps(pet)) == pet


def test_damaged_pet_fields_never_raise():
    """Missing, wrongly typed or hostile fields give neutral values: no exception, no crash of the snapshot.
    The save is another program's file, so every field is untrusted."""
    pet = pets.compact({"CustomName": 5, "CreatureID": "^bad id!", "Trust": "high", "Traits": "no",
                        "PetBattlerMoves": [None, 3, "^OK"], "PetBattlerCoreStatClassOverrides": [None],
                        "UA": "zz", "CreatureSeed": [True, "zz"], "BirthTime": True})
    assert pet["name"] is None and pet["id"] == "" and pet["trust"] == 0.0 and pet["traits"] == []
    assert pet["moves"] == ["OK"] and pet["classes"] == ["?"] and pet["ua"] is None and pet["seeds"][0] is None
    assert pet["born"] is None
    assert pets.compact({})["moves"] == []


def test_all_pets_eggs_and_slots_are_collected_and_bounded():
    """compact_all() keeps pets, eggs and the unlocked/total slot count (11 of 30 in the measured save) and
    cuts a damaged save at MAX_PETS / MAX_EGGS."""
    state = {"Pets": [raw_pet()] * 3 + ["junk"], "Eggs": [raw_pet(CustomName="")] * 2,
             "UnlockedPetSlots": [True] * 10 + [False] * 20}
    out = pets.compact_all(state)
    assert (len(out["pets"]), len(out["eggs"]), out["slots"]) == (3, 2, [10, 30])
    assert pets.compact_all({"Pets": [raw_pet()] * 500})["pets"].__len__() == pets.MAX_PETS
    assert pets.compact_all({})["slots"] == [0, 0]


def test_the_texts_a_pet_row_shows():
    """Name (or 'Cow (unnamed)'), age in days, trust as a percentage, the raw signed traits and the three
    stat classes in the order Combat Effectiveness / Health / Agility. The traits are shown raw because
    their meaning is not confirmed."""
    pet = pets.compact(raw_pet())
    assert pets.display_name(pet) == "Unzy Bunzy Bowa"
    assert pets.display_name(pets.compact(raw_pet(CustomName=""))) == "Cow (unnamed)"
    assert pets.age_days(pet, NOW) == (NOW - 1_788_448_379) // 86_400
    assert pets.age_days(pets.compact(raw_pet(BirthTime=0)), NOW) is None
    assert pets.trust_text(pet) == "75 %"
    assert pets.traits_text(pet) == "+0.25 / -0.73 / -0.16" and pets.traits_text(pets.compact({})) == "–"
    assert pets.stat_classes_text(pet) == "Combat Effectiveness C, Health C, Agility C"


def test_abilities_are_listed_with_the_games_description_when_it_is_known():
    """move_lines() pairs each template with its class and description from the move table, and leaves a
    template the table lacks as its bare id - never an invented description."""
    book = pets.PetBook()
    book.moves = pets.parse_moves(move_table())
    lines = pets.move_lines(pets.compact(raw_pet()), book)
    assert lines[0] == "ATTACK_DUST (ATTACK): Direct damage of one affinity"
    assert lines[1] == "AFF_SPEED_THEM", "not in the table: shown as its id, nothing made up"
    assert lines[2] == "SELF_HOT (HEAL): Heal over time on self"


def test_a_pet_finds_where_its_species_was_first_scanned():
    """first_scan() joins a pet to the animal discovery record with the same creature seed (VP index 0) and
    returns None for a pet whose seed no record has - the join that tells where a companion's kind was found."""
    pet = pets.compact(raw_pet())
    record = {"k": "Animal", "a": 5, "m": True}
    assert pets.first_scan(pet, {0x320E447D6296A867: record}) is record
    assert pets.first_scan(pet, {1: record}) is None
    assert pets.first_scan(pets.compact({}), {1: record}) is None


def test_empty_slots_are_not_companions():
    """Pets and Eggs are fixed-size arrays in the save: the measured one holds 30 and 18 entries, of which 11 pets
    and 4 eggs exist (11 unlocked slots) and the rest are blank records (CreatureID '^', trust 0). Counting them
    showed 19 phantom 'Creature (unnamed)' companions and '30 of 11 slots' on the first live run against the real
    save. Blank records are dropped; a real one with no name stays."""
    blank = {"CreatureID": "^", "Trust": 0.0, "CreatureType": {"CreatureType": "None"}, "Biome": {"Biome": "Lush"}}
    state = {"Pets": [raw_pet(), raw_pet(CustomName="")] + [dict(blank) for _ in range(28)],
             "Eggs": [raw_pet(CreatureID="^CAT")] + [dict(blank) for _ in range(17)],
             "UnlockedPetSlots": [True] * 11 + [False] * 19}
    out = pets.compact_all(state)
    assert (len(out["pets"]), len(out["eggs"]), out["slots"]) == (2, 1, [11, 30])
    assert pets.display_name(out["pets"][1]) == "Cow (unnamed)"


def test_type_and_personality_tooltips_use_the_games_words_and_admit_what_is_unknown():
    """The Type tooltip explains Passive/Prey/Predator and says so for an unknown type; the personality tooltip names
    the game's six words (game language when read) and states that the mapping of the three values is unconfirmed."""
    from nms_connector import companions_view
    book = pets.PetBook.from_texts({"UI_PET_HELPFUL_RATING": "Helpfulness", "PREY1": "Prey"},
                                   {"UI_PET_HELPFUL_RATING": "Hilfsbereitschaft", "PREY1": "Beute"}, "german")
    assert pets.type_note("Prey", book).startswith("Prey (Beute):")
    assert "no description" in pets.type_note("Grunt", book) and pets.type_note("Predator", pets.PetBook()).startswith("Predator:")
    names = pets.trait_names(book)
    assert names[0] == "Helpfulness (Hilfsbereitschaft)" and names[5] == "Devotion" and len(names) == 6
    hint = companions_view.traits_hint(book, pets.compact({"Traits": [0.25, -0.73, -0.16]}))
    assert "inferred" in hint and "Hilfsbereitschaft (+)" in hint and "+0.25 / -0.73 / -0.16" in hint
    assert pets.wanted_key("UI_PET_GENTLENESS_RATING") and not pets.wanted_key("UI_PET_GENTLENESS_RATING_COLOUR")


def test_personality_reads_the_three_values_as_the_games_percentages():
    """The player's in-game readings fix the axes: Unzy Bunzy Bowa 25 % Helpfulness / 73 % Gentleness / 16 % Devotion,
    Little Cute Monster 23 % Playfulness / 77 % Gentleness / 16 % Devotion, Mantissa 79 % Playfulness / 38 %
    Gentleness / 20 % Independence (the German names are used when the game files were read in German)."""
    german = pets.PetBook.from_texts(
        {"UI_PET_HELPFUL_RATING": "Helpfulness", "UI_PET_PLAYFUL_RATING": "Playfulness", "UI_PET_GENTLENESS_RATING": "Gentleness",
         "UI_PET_ATTACHMENT_RATING": "Devotion", "UI_PET_INDEPENDENCE_RATING": "Independence", "UI_PET_AGGRESSION_RATING": "Aggression"},
        {"UI_PET_HELPFUL_RATING": "Hilfsbereitschaft", "UI_PET_PLAYFUL_RATING": "Verspieltheit", "UI_PET_GENTLENESS_RATING": "Sanftmut",
         "UI_PET_ATTACHMENT_RATING": "Hingabe", "UI_PET_INDEPENDENCE_RATING": "Selbstständigkeit", "UI_PET_AGGRESSION_RATING": "Aggression"},
        "german")
    unzy = pets.compact({"Traits": [0.2489, -0.7319, -0.1603]})
    little = pets.compact({"Traits": [-0.23, -0.77, -0.16]})
    mantissa = pets.compact({"Traits": [-0.79, -0.38, 0.20]})
    assert pets.personality_text(unzy, german) == "Hilfsbereitschaft 25% / Sanftmut 73% / Hingabe 16%"
    assert pets.personality_text(little, german) == "Verspieltheit 23% / Sanftmut 77% / Hingabe 16%"
    assert pets.personality_text(mantissa, german) == "Verspieltheit 79% / Sanftmut 38% / Selbstständigkeit 20%"
    assert pets.personality_text(pets.compact({"Traits": [0.1, 0.77, 0.3]}), pets.PetBook()) == "Helpfulness 10% / Aggression 77% / Independence 30%"
    assert pets.personality_text(pets.compact({}), pets.PetBook()) == "–"
