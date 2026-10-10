"""The planet *Subtype* (plugin 0.15.0): the sub-biome number the game records for every planet and nothing used.

Measured on the real history (192 planets): a global 1-27 enum shared across biomes (54 distinct (biome, subtype)
pairs), no `Waterworld` biome among them, and no planet text that mentions water. The game files do have ocean
variants of other biomes (barrenoceanbiome, scorchoceanbiome, toxicoceanbiome), so ocean worlds are stored as a
subtype - but which numbers they are is not known and could not be derived from the stored type text, so the column
shows the number as recorded and `OCEAN_SUBTYPES` stays empty until an in-game observation confirms it.
"""
from nms_connector import planet_search, planets_view

PLANET = {"name": "Dusty", "index": 1, "biome": "Lush", "biome_subtype": 21, "size": "Medium",
          "common": None, "uncommon": None, "rare": None, "extra": [], "info": {}}


class Texts:
    """Just enough of planets_view.Texts for a row."""

    @staticmethod
    def description(info):
        return "Lush Planet"

    @staticmethod
    def key(*values):
        return "–"

    @staticmethod
    def item(value):
        return "–"

    @staticmethod
    def items(values):
        return "–"


def test_the_planet_table_has_a_subtype_column_with_the_recorded_number():
    """Every planet row ends with its recorded sub-biome number (sortable as a number, with a tooltip saying
    what it is and that the ocean numbers are not confirmed); a planet recorded without one shows a dash. The new
    column is last, so no existing column moved."""
    assert planets_view.PLANET_COLUMNS[-1] == "Subtype" and planets_view.PLANET_COLUMNS[0] == "Planet"
    row = planets_view._planet_row(Texts(), PLANET, None, 2)
    assert len(row) == len(planets_view.PLANET_COLUMNS)
    cell = row[-1]
    assert cell["text"] == "21" and cell["sort"] == 21 and "not confirmed" in cell["hint"]
    assert planets_view._planet_row(Texts(), dict(PLANET, biome_subtype=None), None, 2)[-1] == "–"
    assert planets_view._planet_row(Texts(), dict(PLANET, biome_subtype=True), None, 2)[-1] == "–"


def test_ocean_subtypes_are_empty_until_an_observation_confirms_them():
    """OCEAN_SUBTYPES is empty on purpose: a guessed number would label ordinary planets as oceans, and the
    persona would repeat it. A waterworld biome is searched as an ocean world already (via the world types)."""
    assert planets_view.OCEAN_SUBTYPES == frozenset()
    assert planets_view.is_ocean(dict(PLANET, biome="Waterworld")) is True
    assert planets_view.is_ocean(PLANET) is False


def test_a_confirmed_ocean_subtype_makes_the_planet_searchable_as_an_ocean(monkeypatch):
    """Once a number is confirmed (here: 21), planets with that subtype - whatever their biome - are found by
    'ocean' / 'ozean' / 'water' / 'wasser', and the others are not. This is the whole of the ocean search, so it
    switches on with one constant and every planet already in the history is classified retroactively."""
    monkeypatch.setattr(planets_view, "OCEAN_SUBTYPES", frozenset({21}))
    assert planets_view.is_ocean(PLANET) is True
    assert planets_view.is_ocean(dict(PLANET, biome_subtype=2)) is False
    assert {"ocean", "ozean", "water", "wasser"} <= planet_search.ocean_words()
