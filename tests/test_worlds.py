"""World types in the game's words (worlds.py) and the German-aware planet search (planet_search.stem, world words):
asked for 2026-10-06 after "Habe ich bereits eine stickige Welt entdeckt?" was searched as "sticky"."""

from nms_connector import planet_search, worlds

EN = {"DEAD2": "Dead %PLANETCLASS%", "DEAD3": "Empty %PLANETCLASS%", "DEAD9": "Airless %PLANETCLASS%",
      "WEATHER_DEAD7": "Airless", "WEATHER_DEAD3": "No Atmosphere", "UI_VISIT_CLIMATE_DEAD": "<TECHNOLOGY>airless<>",
      "TOXIC1": "Toxic %PLANETCLASS%", "WEATHER_TOXIC3": "Toxic Rain", "WEATHER_TOXICEXTREME2": "Toxic Superstorm",
      "UI_VISIT_CLIMATE_TOXIC": "<TRADEABLE>toxic<>",
      "SWAMPBIOME1": "Marshy %PLANETCLASS%", "WEATHER_SWAMP_CLEAR9": "Sweaty Drizzle",
      "LUSH1": "Rainy %PLANETCLASS%", "WEATHER_LUSH2": "Light Rain", "WEATHER_LAVA1": "Ash Rain",
      "WEATHER_BARREN1": "Dust Rain"}
DE = {"DEAD2": "Toter %PLANETCLASS%", "DEAD3": "Leerer %PLANETCLASS%", "DEAD9": "Stickiger %PLANETCLASS%",
      "WEATHER_DEAD7": "Stickig", "WEATHER_DEAD3": "Keine Atmosphäre", "UI_VISIT_CLIMATE_DEAD": "<TECHNOLOGY>stickig<>",
      "TOXIC1": "Giftiger %PLANETCLASS%", "WEATHER_TOXIC3": "Giftiger Regen", "WEATHER_TOXICEXTREME2": "Giftiger Supersturm",
      "UI_VISIT_CLIMATE_TOXIC": "<TRADEABLE>giftig<>",
      "SWAMPBIOME1": "Marschland-%PLANETCLASS%", "WEATHER_SWAMP_CLEAR9": "Stickiger Sprühregen",
      "LUSH1": "Regnerischer %PLANETCLASS%", "WEATHER_LUSH2": "Leichter Regen", "WEATHER_LAVA1": "Ascheregen",
      "WEATHER_BARREN1": "Staubregen"}


def book() -> worlds.WorldBook:
    return worlds.WorldBook.from_texts(EN, DE, "german")


def test_names_and_weathers_are_read_per_world_type_in_both_languages():
    """Planet-type names (prefix + digits, %PLANETCLASS% -> Planet), weathers (EXTREME marked) and the climate word
    are grouped by world type, English beside the game's language, markup removed."""
    b = book()
    dead = b.worlds["dead"]
    assert [(n["en"], n["local"]) for n in dead["names"]] == [
        ("Dead Planet", "Toter Planet"), ("Empty Planet", "Leerer Planet"), ("Airless Planet", "Stickiger Planet")]
    assert dead["climate"]["en"] == "airless" and dead["climate"]["local"] == "stickig"
    assert [w["extreme"] for w in b.worlds["toxic"]["weathers"]] == [False, True]


def test_stickig_is_explained_as_airless_not_sticky():
    """The question that went wrong: 'stickige' is the German game's 'Airless' - an airless (dead) world - and the
    swamp weather 'Stickiger Sprühregen' is named as a second meaning; question words say nothing."""
    lines = book().explain("Habe ich bereits eine stickige Welt entdeckt?")
    assert len(lines) == 1
    assert "'Stickiger Planet' = 'Airless Planet'" in lines[0] and "airless (dead) worlds" in lines[0]
    assert "no atmosphere" in lines[0] and "planet records: Dead" in lines[0]
    assert "also the weather 'Stickiger Sprühregen' = 'Sweaty Drizzle' on swamp worlds" in lines[0]


def test_inflected_and_generic_words():
    """'giftigen' (inflected) finds toxic worlds; a weather word shared by many world types ('Regen') and the
    generic 'Planeten' are not explained - they do not tell which world is meant."""
    b = book()
    assert "toxic worlds" in b.explain("Wo gibt es giftigen Planeten?")[0]
    assert b.explain("Regen auf Planeten") == []


def test_biome_words_link_every_name_variant_but_not_weathers():
    """A planet record's biome gets the words of all its type names and the climate word (so 'stickige' finds a
    'Leerer Planet'), but not its weathers: the swamp weather 'Stickiger Sprühregen' must not make swamps airless."""
    words = book().biome_words()
    assert {"stickiger", "leerer", "toter", "airless", "stickig"} <= words["Dead"]
    assert "stickiger" not in words["Swamp"]
    exotic = worlds.WorldBook.from_texts({"GLITCHBIOME1": "Toxic Anomaly", "UI_VISIT_CLIMATE_WEIRD": "unusual"},
                                         {"GLITCHBIOME1": "Giftige Anomalie", "UI_VISIT_CLIMATE_WEIRD": "ungewöhnlich"})
    assert exotic.biome_words()["Exotic"] == {"unusual", "ungewoehnlich"}       # not 'giftige' for every exotic planet


def test_stem_drops_german_adjective_endings_only_from_long_words():
    """'stickige' -> 'stickig', 'giftigen' -> 'giftig', 'toten' -> 'tot'; at least three letters stay and short
    words keep their ending ('rote' stays: 'rot' would be too short a stem for a four-letter word)."""
    assert planet_search.stem("stickige") == "stickig" and planet_search.stem("giftigen") == "giftig"
    assert planet_search.stem("toten") == "tot" and planet_search.stem("rote") == "rote"
    assert planet_search.stem("toxic") == "toxic"


class _Ctx:
    """A planets_view.Context stand-in: recorded planets and their world words."""
    def __init__(self, world_words):
        self.recorded = {1: [{"name": "Leeria", "biome": "Dead"}, {"name": "Moory", "biome": "Swamp"}]}
        self.world_words = world_words
        self.texts = None
        self.sentinel_index = None
        self.origin = None

    def visit(self, key):
        return {}


def test_planet_search_finds_an_airless_planet_by_any_german_form():
    """With the world words, 'stickige Welt' finds the dead planet even though its row says nothing about it, and
    the asking words ('bereits', 'entdeckt') no longer count as things a planet could be."""
    ctx = _Ctx(book().biome_words())
    index = planet_search.PlanetIndex(ctx, lambda texts, p, v, s: [p["name"], p["biome"]], lambda key, v: "Sol")
    wanted, found = index.best("Habe ich bereits eine stickige Welt entdeckt?")
    assert wanted == ["stickige"] and [e["planet"]["name"] for e, _ in found] == ["Leeria"]
    assert [e["planet"]["name"] for e, _ in index.search("toten")] == ["Leeria"]


def test_world_documents_are_split_by_language():
    """One document per world type and language: the English one has the English names and weathers only, the
    German one the German title, names, weathers, facts and resources (as the game names them: Flüsterndes Ei,
    Biologische Abscheulichkeit, Verrostetes Metall, Atmosphärenverarbeitungsanlage)."""
    from nms_connector import game_terms
    items = {"SPACEGUNK3": {"en": "Rusted Metal", "local": "Verrostetes Metall"}, "TOXIC1": {"en": "Ammonia", "local": "Ammoniak"},
             "PLANT_TOXIC": {"en": "Fungal Mould"}, "GAS3": {"en": "Nitrogen", "local": "Stickstoff"}}
    docs = book().documents(items.get, game_terms.GameTerms(language="german"))
    en = docs["English/Worlds/Airless (dead) worlds.md"]
    assert worlds.GENERATED_MARK in en and "language: en" in en and "- Airless Planet" in en
    assert "Stickig" not in en and "Rusted Metal" in en and "Whispering Eggs" in en
    de = docs["Deutsch/Welten/Stickige Welten (tot, ohne Atmosphäre).md"]
    assert "language: de" in de and "- Stickiger Planet" in de and "- Stickig" in de and "Airless" not in de.split("## ")[1]
    assert "Verrostetes Metall" in de and "Biologische Abscheulichkeiten" in de and "Flüsterndes Ei" in de
    toxic = docs["Deutsch/Welten/Giftige Welten.md"]
    assert "Ammoniak" in toxic and "Gas für die Atmosphärenverarbeitungsanlage: Stickstoff" in toxic
    assert "(Extremwetter - Stürme)" in toxic
    assert worlds.load(None).error == "game installation not found"


def test_the_persona_is_told_how_many_planets_match_when_the_list_is_cut():
    """Live test 2026-10-06: with 11 toxic planets and only the nearest 8 listed, the model answered "8 giftige
    Planeten". The first line now states the total and that only the nearest are listed."""
    from nms_connector import companion
    ctx = _Ctx(book().biome_words())
    ctx.recorded = {1: [{"name": f"Gift {i}", "biome": "Toxic"} for i in range(companion.MAX_PLANETS + 3)]}

    class Conn:
        tables = None
    comp = companion.PluginCompanion(Conn())
    from nms_connector import planets_view
    original = planets_view.planet_index
    planets_view.planet_index = lambda c: planet_search.PlanetIndex(c, lambda t, p, v, s: [p["name"], p["biome"]],
                                                                    lambda k, v: "Sol")
    try:
        lines = comp.planet_lines("Welche giftigen Planeten kenne ich?", {"welche", "giftigen", "planeten"}, ctx)
    finally:
        planets_view.planet_index = original
    assert lines[0].startswith(f"{companion.MAX_PLANETS + 3} recorded planets match giftigen")
    assert lines[0].endswith(f"the nearest {companion.MAX_PLANETS} of them:") and len(lines) == companion.MAX_PLANETS + 1


def test_world_documents_open_with_a_german_sentence():
    """The Codex's meaning-based lookup embeds a document's first passage: the German airless document says right
    at the top that a 'stickige Welt' is a world without atmosphere (not sticky)."""
    from nms_connector import game_terms
    dead = book().documents({}.get, game_terms.GameTerms(language="german"))[
        "Deutsch/Welten/Stickige Welten (tot, ohne Atmosphäre).md"]
    head = dead.split("## ", 1)[0]
    assert "Eine stickige Welt" in head and "nicht klebrig" in head


