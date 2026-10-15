"""Tests for the galaxies: the 256 names, the kind each one has, the Galaxies tab and the persona's lines
(galaxies.py, planets_view.galaxies_sections, PluginCompanion.galaxy_lines)."""

import json

from nms_connector import galaxies, galaxy, planets_view
from nms_connector.companion import PluginCompanion
from nms_connector.history import PlanetHistory
from nms_connector.summary import galaxy_name

EUCLID = 0x0620002925E80                   # RealityIndex 0
HILBERT = 0x0620102925E80                  # RealityIndex 1
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


def context(tmp_path, live=None, bases=None):
    history = PlanetHistory(tmp_path / "h.json")
    history.system_names = {EUCLID: "Delta Sol", HILBERT: "Kayana", CALYPSO: "Lipashc-Nogh"}
    history.economies = {EUCLID: {"economy": "Mining", "read_at": "t"}, CALYPSO: {"economy": "Trading", "read_at": "t"}}
    return planets_view.Context(live or Live(), history, {EUCLID: {"planets": {}}, CALYPSO: {"planets": {}}},
                                FakeTexts(), None, bases=bases or [])


def test_every_galaxy_is_named_and_numbered():
    """All 256 names are recorded (the game's files name only the first five), in address order: index 0 is
    Euclid, which the game calls galaxy 1. An index beyond them keeps an honest "Galaxy #n"."""
    assert galaxies.count() == 256 and len(set(galaxies.NAMES)) == 256
    assert galaxies.NAMES[:3] == ["Euclid", "Hilbert Dimension", "Calypso"]
    assert galaxies.NAMES[9] == "Eissentam" and galaxies.NAMES[255] == "Odyalutai"
    assert galaxies.name(0) == "Euclid" and galaxies.number(0) == 1
    assert galaxies.name(2) == "Calypso" and galaxies.number(2) == 3
    assert galaxies.name(300) == "Galaxy #301" and galaxies.label(300) == "Galaxy #301"
    assert galaxies.name(None) == "unknown" and galaxies.name(True) == "unknown"
    assert galaxies.label(None) == "unknown galaxy"
    # The whole plugin names galaxies through this list now (addresses in the save, bases, visited systems).
    assert galaxy_name(2) == "Calypso" and galaxy_name(136) == "Urckiansi" and galaxy_name(None) == "unknown"


def test_a_galaxys_kind_follows_from_its_number():
    """The kind sits at the same six places of every block of twenty galaxy numbers. The rule is derived from
    the galaxies the wiki labels, and it must reproduce the recorded totals (26 harsh, 26 empty, 25 lush) -
    that agreement is the only check there is, since the game's files hold none of this."""
    labelled = {3: "harsh", 7: "empty", 10: "lush", 12: "empty", 15: "harsh", 19: "lush",
                23: "harsh", 27: "empty", 30: "lush", 32: "empty", 35: "harsh", 39: "lush",
                43: "harsh", 47: "empty", 50: "lush", 52: "empty", 55: "harsh", 59: "lush",
                63: "harsh", 67: "empty", 70: "lush"}
    for number, expected in labelled.items():
        assert galaxies.kind(number - 1) == expected, number
    assert galaxies.kind(0) == "normal" and galaxies.kind(1) == "normal"      # Euclid, Hilbert Dimension
    assert galaxies.kind_counts() == {"normal": 179, "lush": 25, "harsh": 26, "empty": 26}
    assert sum(galaxies.kind_counts().values()) == 256
    assert galaxies.of_kind("lush")[0] == 9 and galaxies.of_kind("harsh")[0] == 2
    # Nonsense never gets a kind of its own: it counts as a normal galaxy rather than raising.
    assert galaxies.kind(999) == "normal" and galaxies.kind(None) == "normal" and galaxies.kind(-1) == "normal"
    assert galaxies.label(2) == "Calypso (galaxy 3 of 256, harsh)"
    assert galaxies.kind_label(9) == "Lush"


def test_the_research_file_covers_every_kind():
    """The sourced prose (what differs, the game's own descriptor words) lives in research/galaxies.json and
    is what the page and the persona read; a kind missing from it would silently lose its explanation."""
    research = galaxies.load_research()
    assert research.get("sources") and research.get("unchanged")
    for kind in (galaxies.NORMAL, galaxies.LUSH, galaxies.HARSH, galaxies.EMPTY):
        entry = research["kinds"][kind]
        assert entry["differences"] and entry["descriptors"] and entry["hologram"]
        index = galaxies.of_kind(kind)[0]
        assert galaxies.kind_facts(index, research)[:-1] == entry["differences"]
        assert galaxies.kind_facts(index, research)[-1] == galaxies.UNCHANGED
        assert galaxies.descriptors(index, research) == entry["descriptors"]
    # Without the file the built-in one-liner stands in, and nothing raises.
    assert galaxies.kind_facts(2, {}) == [galaxies.KINDS["harsh"]["text"], galaxies.UNCHANGED]
    assert galaxies.descriptors(2, {}) == []
    assert galaxies.load_research(tmp := galaxies.RESEARCH_FILE.with_name("nope.json")) == {} and tmp


def test_the_galaxies_tab_shows_where_you_are_and_where_you_have_been(tmp_path):
    """Systems -> Galaxies: the galaxy you are in with what its kind changes, a row per galaxy your save has
    touched (the one you are in marked), and a table of the four kinds. The counts come from the addresses,
    so they need no game running."""
    ctx = context(tmp_path, bases=[{"name": "Home", "system": EUCLID}])
    sections = planets_view.galaxies_sections(ctx, galaxies.load_research())
    here, table, hearsay, kinds, note = sections
    # Hilbert Dimension is in this save only through a name read out of the galaxy map's cache.
    assert hearsay["type"] == "text" and "1 further galaxies (Hilbert Dimension)" in hearsay["text"]
    items = {i["label"]: i["value"] for i in here["items"]}
    assert here["id"] == planets_view.GALAXY_HERE_ID
    assert items["Galaxy"] == "Calypso - number 3 of 256"
    assert items["Kind"].startswith("Harsh (the game's own words: Burning")
    assert "hologram is red" in items["On the galaxy map"]
    assert "toxic, scorched, frozen and irradiated planets are markedly more common" in items["What that changes"]
    assert galaxies.UNCHANGED in items["What that changes"]
    assert items["Next galaxy through the core"].startswith("Hesperius Dimension (galaxy 4 of 256, normal)")

    assert table["id"] == planets_view.GALAXIES_ID and table["title"] == "Your galaxies (2)"
    columns = {name: i for i, name in enumerate(table["columns"])}
    rows = {r[columns["Galaxy"]]: r for r in table["rows"]}
    assert set(rows) == {"Euclid", "Calypso"}          # Hilbert Dimension has nothing solid in it
    assert rows["Calypso"][columns["Here"]] == "yes" and rows["Euclid"][columns["Here"]] == ""
    assert rows["Calypso"][columns["Number"]] == 3 and rows["Calypso"][columns["Kind"]] == "Harsh"
    assert rows["Euclid"][columns["Your bases"]] == 1 and rows["Euclid"][columns["Systems"]] == 1
    assert rows["Euclid"][columns["Names from the map"]] == 1
    assert rows["Euclid"][columns["Economies read"]] == 1

    assert kinds["id"] == planets_view.GALAXY_KINDS_ID and len(kinds["rows"]) == 4
    assert [r[0] for r in kinds["rows"]] == ["Normal", "Lush", "Harsh", "Empty"]
    assert [r[1] for r in kinds["rows"]] == [179, 25, 26, 26]
    assert note["type"] == "text" and "3 and 15 are harsh" in note["text"]


def test_without_a_save_the_galaxy_panel_says_so(tmp_path):
    """Before a save has been read there is no address to take a galaxy from, and the panel says that instead
    of claiming Euclid - the plugin's rule everywhere: no invented values."""
    class Nowhere(Live):
        current_system = None

    ctx = planets_view.Context(Nowhere(), PlanetHistory(tmp_path / "h.json"), {}, FakeTexts(), None)
    sections = planets_view.galaxies_sections(ctx)
    assert sections[0]["type"] == "text" and "once a save has been read" in sections[0]["text"]
    assert sections[1]["rows"] == [] and "comes from its address" in sections[1]["empty"]
    # The kinds reference stands on its own, without a save.
    assert len(sections[2]["rows"]) == 4


def test_the_persona_is_told_about_the_galaxy_only_when_asked(tmp_path):
    """The lines reach the model on a galaxy word: which galaxy, what its kind changes, which galaxies the
    save has been to and what comes next. Without such a word they stay out - every question about space
    would otherwise carry them instead of what it asked for."""
    ctx = context(tmp_path)
    companion = object.__new__(PluginCompanion)
    lines = companion.galaxy_lines({"which", "galaxy", "am", "i", "in"}, ctx, CALYPSO)
    assert lines[0].startswith("You are in Calypso (galaxy 3 of 256, harsh):")
    assert "toxic" in lines[0] and galaxies.UNCHANGED in lines[0]
    assert lines[1] == "The next galaxy through the galactic core is Hesperius Dimension (galaxy 4 of 256, normal)."
    assert lines[2].startswith("Galaxies your save has been to (2):")
    assert "Calypso (galaxy 3 of 256, harsh): 1 system(s)" in lines[2]
    assert lines[-1].startswith("There are 256 galaxies; resources, recipes")
    assert companion.galaxy_lines({"how", "much", "copper"}, ctx, CALYPSO) == []
    # Asked in German, or by a galaxy's name, and without a save position.
    assert companion.galaxy_lines({"welche", "galaxie"}, ctx, CALYPSO)
    assert companion.galaxy_lines({"is", "eissentam", "better"}, ctx, CALYPSO)
    nowhere = companion.galaxy_lines({"galaxy"}, ctx, None)
    assert nowhere and not nowhere[0].startswith("You are in")


def test_the_type_pattern_is_recorded_with_its_sources():
    """The pattern is a derivation, not a reading of the game's files, so the file that states it must also
    state where it comes from and how it was checked - the rule for every researched fact here."""
    raw = json.loads(galaxies.RESEARCH_FILE.read_text(encoding="utf-8"))
    pattern = raw["pattern"]
    assert "modulo 20" in pattern["rule"] and "derivation" in pattern and "26 harsh" in pattern["check"]
    assert any("miraheze" in url for url in raw["sources"])
    assert raw["caveats"] and any("probability" in c for c in raw["caveats"])


def test_visited_systems_have_their_own_bit_layout():
    """Found on 2026-10-15 while adding the Galaxies tab: `PlayerStateData.VisitedSystems` is **not** packed
    like `PlanetUA` and the discovery records. Y and Z are swapped and the system index and galaxy sit higher
    up, so reading it the old way put the galaxy byte inside the system index - the real save then claimed
    167 galaxies instead of the 3 it has been to, with wrong voxels, portal addresses and distances for every
    system known only from that list.

    The entry below is the first one of the real save; the save's own `UniverseAddress` states the same
    system in plain JSON (-384, 2, -1755, system 98, Euclid), which is what pins the layout down.
    """
    from nms_connector import memory
    from nms_connector.summary import address_portal, unpack_address

    entry = 0x00106292502E80
    assert memory.unpack_visited(entry) == {"VoxelX": -384, "VoxelY": 2, "VoxelZ": -1755,
                                            "SolarSystemIndex": 98, "RealityIndex": 0}
    key = memory.visited_key(entry)
    assert key == 0x620002925E80                     # the canonical key the rest of the plugin uses
    assert address_portal(unpack_address(key)) == "006202925E80"
    assert galaxy.galaxy_of(key) == 0 and galaxies.name(0) == "Euclid"
    # Read the old way, this very entry claimed galaxy index 98 - Hicanpaav, which this save has never seen -
    # and a voxel Z of 1282 instead of -1755, because every field came out of the wrong bits.
    assert (entry >> 32) & 0xFF == 98 and galaxies.name(98) == "Hicanpaav"   # index 98 = galaxy 99
    assert ((entry >> 12) & 0xFFF) == 1282

    # A galaxy in the high byte survives the conversion: Calypso (index 2) stays Calypso.
    calypso = entry | (2 << 48)
    assert memory.unpack_visited(calypso)["RealityIndex"] == 2
    assert galaxy.galaxy_of(memory.visited_key(calypso)) == 2
    # The unknown nibble above the system index is ignored, not read as a planet.
    assert memory.visited_key(entry | (0xF << 44)) == key


def test_the_save_states_which_galaxies_you_reached(tmp_path):
    """A teleport endpoint exists only where you have been (a base you built, a station you docked at), so
    the save itself records the other galaxies you reached - two of them on the real save, in Hilbert
    Dimension and Calypso. They count as visited systems and are shown per galaxy."""
    from nms_connector.history import visits_from_save

    save = {"BaseContext": {"PlayerStateData": {
        "VisitedSystems": [],
        "TeleportEndpoints": [
            {"UniverseAddress": {"RealityIndex": 0, "GalacticAddress": {
                "VoxelX": -384, "VoxelY": 2, "VoxelZ": -1755, "SolarSystemIndex": 98, "PlanetIndex": 0}},
             "Name": "Reat Kay's Origin Home", "TeleporterType": "Base"},
            {"UniverseAddress": {"RealityIndex": 2, "GalacticAddress": {
                "VoxelX": -100, "VoxelY": 1, "VoxelZ": 200, "SolarSystemIndex": 45, "PlanetIndex": 0}},
             "TeleporterType": "Spacestation"},
            {"UniverseAddress": {"GalacticAddress": {}}},                 # unusable: no voxel at all
            {"Name": "no address"}, "not a dict",
        ]}}}
    visits = visits_from_save(save)
    assert len(visits) == 2
    euclid = visits[0x620002925E80]
    assert euclid["visited"] is True and euclid["teleport"] == "Reat Kay's Origin Home"
    other = next(v for k, v in visits.items() if galaxy.galaxy_of(k) == 2)
    assert other["teleport"] == "Spacestation"      # no name: the kind of endpoint stands in

    ctx = planets_view.Context(Live(), PlanetHistory(tmp_path / "h.json"), visits, FakeTexts(), None)
    counts = planets_view.galaxy_counts(ctx)
    assert counts[0]["teleports"] == 1 and counts[2]["teleports"] == 1
    table = planets_view.galaxies_sections(ctx)[1]
    column = table["columns"].index("Teleport endpoints")
    assert {r[1]: r[column] for r in table["rows"]} == {"Euclid": 1, "Calypso": 1}
