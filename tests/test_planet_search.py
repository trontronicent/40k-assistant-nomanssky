"""Tests for the planet search (planet_search.py): the page's search field, its action and the persona's lines."""

from nms_connector import planet_search, planets_view
from nms_connector.history import PlanetHistory

HERE = 0x0620002925E80
NEAR = 0x0D60002925E80


class Live:
    status, error, current, current_source, current_system = "ok", None, None, "planets", HERE


class GameData:
    """Two languages, as on the player's German game (texts read 2026-10-05)."""
    ready, language, language_label = True, "german", "Deutsch"
    trading, trading_source = None, "built-in"
    items = {"YELLOW2": {"en": "Copper", "local": "Kupfer"}, "LAND1": {"en": "Ferrite Dust", "local": "Ferritstaub"},
             "TOXIC1": {"en": "Ammonia", "local": "Ammoniak"}}
    TEXTS = {"SCORCHED3": {"en": "Scorched %PLANETCLASS%", "local": "Sengend heißer %PLANETCLASS%"},
             "TOXIC2": {"en": "Toxic %PLANETCLASS%", "local": "Giftiger %PLANETCLASS%"},
             "PLANETCLASS1": {"en": "Planet", "local": "Planet"},
             "WEATHER_HEAT9": {"en": "Dangerously Hot", "local": "Gefährlich heiß"},
             "WEATHER_TOX1": {"en": "Toxic Rain", "local": "Giftiger Regen"}}

    def lookup(self, item_id):
        return self.items.get(str(item_id).lstrip("^").split("#")[0])

    def icon_name(self, item_id):
        return None

    def text(self, key):
        return self.TEXTS.get(key)


def planet(name, system, index, description, weather, common, rare, biome="Scorched"):
    return {"ua": system | ((index + 1) << 52), "system": system, "index": index, "name": name, "seed": f"{index:x}",
            "common": common, "uncommon": "LAND1", "rare": rare, "extra": [], "biome": biome, "size": "Medium",
            "info": {"description": description, "type": "PLANETCLASS1", "weather": weather}, "confirmed": True,
            "first_seen": "2026-10-05T10:00:00", "last_seen": "2026-10-05T10:00:00"}


def context(tmp_path):
    history = PlanetHistory(tmp_path / "h.json")
    for p in (planet("Aphaste Delta", NEAR, 0, "SCORCHED3", "WEATHER_HEAT9", "YELLOW2", "LAND1"),
              planet("Anzak", HERE, 1, "SCORCHED3", "WEATHER_HEAT9", "YELLOW2", "LAND1"),
              planet("Gifthorn", HERE, 2, "TOXIC2", "WEATHER_TOX1", "YELLOW2", "TOXIC1", biome="Toxic")):
        history.planets[f"{p['ua']}:{p['name']}"] = p
    history.system_names = {HERE: "Delta Sol", NEAR: "Occultimo"}
    return planets_view.Context(Live(), history, {}, GameData(), None)


def test_words_fold_umlauts_and_sharp_s_and_question_words_drop_out():
    """'Sengend heißer' and 'sengend heisser' are the same words; a chat question keeps only what a planet can be
    searched by (no 'wo', 'gibt', 'planeten')."""
    assert planet_search.words("Sengend heißer Planet, Übergroß") == ["sengend", "heisser", "planet", "uebergross"]
    assert planet_search.terms("Wo gibt es sengend heiße Planeten?", drop_question_words=True) == ["sengend", "heisse"]
    assert planet_search.terms("a an") == []


def test_the_search_matches_every_word_in_either_language_nearest_first(tmp_path):
    """'sengend heiß' finds the scorched planets by their German type (you are in Delta Sol: its planet first),
    'scorched' by the English one, a word finds longer ones ('heiss' -> 'heißer'), every word must match."""
    index = planets_view.planet_index(context(tmp_path))
    assert [e["planet"]["name"] for e, _ in index.search("sengend heiß")] == ["Anzak", "Aphaste Delta"]
    assert len(index.search("scorched")) == 2 and len(index.search("heiss")) == 2
    assert [e["planet"]["name"] for e, _ in index.search("Ammoniak")] == ["Gifthorn"]
    assert index.search("sengend Ammoniak") == [] and index.search("") == []


def test_the_planets_tab_has_a_search_form_and_clickable_results(tmp_path):
    """Systems -> Planets: a search form; with a query a table of the matches (system, distance, the planet's
    columns) whose rows open the system map."""
    ctx = context(tmp_path)
    assert [s["type"] for s in planets_view.planet_search_sections(ctx, "")] == ["form"]
    form, table = planets_view.planet_search_sections(ctx, "sengend heiß")
    assert form["fields"][0]["value"] == "sengend heiß" and form["action"] == planets_view.SEARCH_PLANETS
    assert table["id"] == planets_view.PLANET_SEARCH_ID and table["row_action"] == planets_view.OPEN_SYSTEM
    assert table["row_keys"] == [f"{HERE:x}", f"{NEAR:x}"] and table["rows"][0][:3] == ["Delta Sol", "this system", "Anzak"]
    tabs = planets_view.systems_tabs(ctx, None, planet_query="toxic")
    planets_tab = next(t for t in tabs["tabs"] if t["id"] == "planets")
    assert [s["type"] for s in planets_tab["sections"]] == ["form", "table", "table"]


def test_the_search_action_takes_untrusted_text_and_clears_with_an_empty_one(tmp_path, monkeypatch):
    """The form's value is cut to MAX_QUERY_CHARS and answers how many planets match; an empty search clears."""
    import asyncio
    from nms_connector import create_plugin
    from test_connector import FakeCtx
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    result = asyncio.run(plugin.action(planets_view.SEARCH_PLANETS, {"query": "  heiss " + "x" * 200}))
    assert result["ok"] and len(plugin.planet_query) == planet_search.MAX_QUERY_CHARS and "0 planet(s)" in result["message"]
    assert asyncio.run(plugin.action(planets_view.SEARCH_PLANETS, {"query": None}))["message"] == "Planet search cleared."
    assert plugin.planet_query == ""


def test_the_persona_gets_the_planets_a_question_describes(tmp_path):
    """'Wo gibt es sengend heiße Planeten?' gives the persona the matching planets with all they are known for,
    nearest first; a question without a planet word gets none; nothing matching is said plainly."""
    from nms_connector.companion import PluginCompanion
    companion = PluginCompanion(None)
    ctx = context(tmp_path)
    lines = companion.planet_lines("Wo gibt es sengend heiße Planeten?", {"wo", "gibt", "es", "sengend", "heiße", "planeten"}, ctx)
    assert lines[0].startswith("2 recorded planets match sengend, heisse") and lines[0].endswith("nearest first:")
    assert lines[1].startswith("- Anzak in Delta Sol (this system): Type: Scorched Planet (Sengend heißer Planet)")
    assert len(lines) == 3
    assert companion.planet_lines("wie viel Kupfer habe ich", {"wie", "viel", "kupfer", "habe", "ich"}, ctx) == []
    none = companion.planet_lines("planets with crystals", {"planets", "with", "crystals"}, ctx)
    assert none[0].startswith("No recorded planet matches crystals")
