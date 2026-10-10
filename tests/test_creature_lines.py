"""What the persona is told about companions and discoveries (nms_connector/creature_lines.py).

The blocks are short by default (the app cuts a plugin's data at 8,000 characters, from the end), grow only for a
question that asks for the detail, and always say what is not known so the model does not fill the gap.
"""
from nms_connector import creature_lines, discoveries, pets
from nms_connector.discoveries import DiscoveryBook
from test_discovery_tabs import NOW, Ctx, book, snapshot
from test_discoveries import PLANET_1


def label_of(row):
    return "Aldrin Reach, planet 1" if row["a"] == PLANET_1 else "Aldrin Reach"


def test_a_pet_question_gets_one_short_line_per_pet_and_what_is_not_known():
    """'How many companions do I have' opens the companions block: the count with the unlocked slots, one line per
    pet (creature, type, biome, trust, age, arena wins, harvest), the eggs by kind and the list of things the game
    data does not hold. Abilities are not spelled out unless asked, to keep the block small."""
    snap = snapshot()
    lines = creature_lines.pet_lines("How many companions do I have?", snap, book(), NOW)
    assert lines[0] == "Companions: 2 (of 10 unlocked slots), eggs 1, arena wins 22"
    cow = next(line for line in lines if "Unzy Bunzy Bowa" in line)
    assert "Cow" in cow and "trust 75 %" in cow and "22 arena wins" in cow
    assert "harvest: Collect Milk -> Fresh Milk / Raw Steak" in cow and "4 abilities" in cow
    assert "ATTACK_DUST" not in cow, "abilities are only spelled out when asked"
    assert "Eggs: 1 Fiend" in lines and lines[-1] == creature_lines.UNKNOWN_PETS


def test_an_ability_or_arena_question_spells_the_abilities_out():
    """'What abilities does Unzy Bunzy Bowa have?' lists the named pet's templates with the game's description,
    and only that pet's - five described moves for every one of 30 pets would blow the 8,000-character cut."""
    snap = snapshot()
    lines = creature_lines.pet_lines("What abilities does Unzy have?", snap, book(), NOW)
    cow = next(line for line in lines if "Unzy Bunzy Bowa" in line)
    assert "abilities: ATTACK_DUST (ATTACK): Direct damage of one affinity" in cow
    other = next(line for line in lines if "Protoroller" in line)
    assert "abilities:" not in other and "ATTACK" not in other


def test_a_pets_own_name_opens_the_block_and_other_questions_do_not():
    """A question that names a pet ('Unzy') is about companions even without the word pet; a question about
    copper, or one with no companion in the save, gets nothing - the block must not appear unasked."""
    snap = snapshot()
    assert creature_lines.pet_lines("Where is Unzy?", snap, book(), NOW)
    assert creature_lines.pet_lines("How much copper do I have?", snap, book(), NOW) == []
    assert creature_lines.pet_lines("my pets", {"companions": {"pets": [], "eggs": [], "slots": [0, 0]}}, book(), NOW) == []
    assert creature_lines.pet_lines("my pets", None, book(), NOW) == []


def test_the_pet_block_is_bounded_for_a_full_roster():
    """Thirty pets with every ability asked for stay under the size budget: lines past MAX_PET_CHARS are
    replaced by one 'and N more' line. The app cuts the data block from the end, which would drop the
    unknowns and the overview first."""
    snap = snapshot()
    crowd = [dict(snap["companions"]["pets"][0], name=f"Pet number {i}", wins=i) for i in range(30)]
    snap["companions"] = {"pets": crowd, "eggs": [], "slots": [30, 30]}
    lines = creature_lines.pet_lines("list all my pets and their abilities in the arena", snap, book(), NOW)
    assert sum(len(line) for line in lines) < creature_lines.MAX_PET_CHARS + 900
    assert any("more companions" in line for line in lines)
    assert lines[-1] == creature_lines.UNKNOWN_PETS


def test_a_discovery_question_gets_counts_names_and_the_limits():
    """'What did I discover and name?' gives the counts split into yours and other players', the named records
    with kind, place, date and who named them, the fact that no creature carries a name, and the limits of the
    data (flags not interpreted, no completion percentage)."""
    snap = snapshot()
    lines = creature_lines.discovery_lines("What did I discover and name?", DiscoveryBook(snap["discoveries"]), label_of)
    assert lines[0].startswith("Your discoveries: ") and "1 creatures" in lines[0] and "from other players" in lines[0]
    assert any("None of the 2 creature records carries a name" in line for line in lines)
    assert any(line.startswith("- Dusty Cactium (planet, Aldrin Reach, planet 1,") and line.endswith("by you)") for line in lines)
    assert lines[-1] == creature_lines.UNKNOWN_DISCOVERIES


def test_a_discovery_question_with_a_word_in_a_name_finds_that_record():
    """'Did I name something Cactium?' lists the matching record; a kind word ('planets I named') narrows to the
    kind. Search is by the words of the question, so nothing needs a list of names in the prompt."""
    snap = snapshot()
    book_ = DiscoveryBook(snap["discoveries"])
    found = creature_lines.discovery_lines("Did I name something Cactium?", book_, label_of)
    assert any("Dusty Cactium" in line for line in found) and not any("Aldrin Reach (system" in line for line in found)
    planets = creature_lines.discovery_lines("Which planets did I name?", book_, label_of)
    assert any("Dusty Cactium" in line for line in planets) and not any("(system," in line for line in planets)


def test_other_questions_get_no_discovery_block():
    """A question about inventory or an empty store gets no discovery lines."""
    snap = snapshot()
    assert creature_lines.discovery_lines("How much copper do I have?", DiscoveryBook(snap["discoveries"]), label_of) == []
    assert creature_lines.discovery_lines("What did I discover?", DiscoveryBook(None), label_of) == []
    assert discoveries.DiscoveryBook(None).named() == [] and pets.PetBook().harvest("COW") == {}
    assert Ctx.visit(1) is None


def test_the_word_name_alone_does_not_open_the_discovery_block():
    """'What is the name of my ship?' must not drag the discovery block into the data (ship and item names are
    everywhere), while 'Did I name a planet?' and 'have I ever named ...' do open it."""
    snap = snapshot()
    book_ = DiscoveryBook(snap["discoveries"])
    assert creature_lines.discovery_lines("What is the name of my ship?", book_, label_of) == []
    assert creature_lines.discovery_lines("Did I name a planet?", book_, label_of)
    assert creature_lines.discovery_lines("Have I ever named a system?", book_, label_of)


def test_the_persona_wiring_passes_the_connectors_books_and_places():
    """PluginCompanion.pet_lines / discovery_lines hand the connector's pet book and discovery book to the pure
    builders and name places through the connector's context - the wiring chat_context calls, tested without
    the whole connector."""
    from nms_connector.companion import PluginCompanion

    snap = snapshot()

    class Tables:
        pets = book()

    class Connector:
        tables = Tables()
        discovery_book = DiscoveryBook(snap["discoveries"])

    companion = PluginCompanion(Connector())
    assert companion.pet_lines("my companions", snap, NOW)[0].startswith("Companions: 2")
    lines = companion.discovery_lines("Which planets did I name?", Ctx())
    assert any(line.startswith("- Dusty Cactium (planet, Aldrin Reach, planet 1,") for line in lines)


def test_a_kind_question_with_no_named_record_says_so_instead_of_listing_other_kinds():
    """'Did I ever name a creature?' on a save where no creature has a name answers that none does, and does not
    fall back to a list of named planets and systems - which the first live run did, answering a different
    question."""
    snap = snapshot()
    lines = creature_lines.discovery_lines("Did I ever name a creature?", DiscoveryBook(snap["discoveries"]), label_of)
    assert any(line == "None of your creatures records carries a name." for line in lines)
    assert not any(line.startswith("- ") for line in lines), lines


def test_naming_words_do_not_become_planet_search_terms():
    """'did', 'name' and 'named' are not planet properties: left in, 'Which planets did I name?' made the planet
    search print 'No recorded planet matches did, name' beside the real answer."""
    from nms_connector import planet_search
    assert {"did", "name", "named", "names"} <= set(planet_search.QUESTION_WORDS)
