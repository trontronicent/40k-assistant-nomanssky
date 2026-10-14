"""Tests for the guild envoy of a region: the pure records (guilds.py), the history file's additive key,
the system details and table cells, and the plugin's recording action with untrusted form values."""

from nms_connector import galaxy, guilds, planets_view
from nms_connector.history import PlanetHistory

DELTA_SOL = 0x0620002925E80               # region (-384, 2, -1755), system 0x062
KAYANA = 0x0B50002925E80                  # same region, another system
FAR_AWAY = 0x0620002935E80                # one voxel over: another region, so another guild


class Live:
    """A connector not reading the running game (no current system)."""

    current_system = None
    status = "not-running"
    error = None
    current = None
    current_source = "planets"


class FakeTexts:
    """Enough of GameData for Context: every item is named by its own id, no text key resolves."""

    def lookup(self, item_id):
        return {"en": item_id, "local": item_id}

    def icon_name(self, item_id):
        return None

    def text(self, key):
        return None


def context(history, visits=None):
    return planets_view.Context(Live(), history, visits or {DELTA_SOL: {"planets": {}}}, FakeTexts(), None)


def test_a_guild_is_recorded_for_the_whole_region_of_a_system(tmp_path):
    """The guild envoy is the region's, not the station's (community finding, see guilds.py), so recording it
    in one system answers every system of that region - marked as inferred there, because it was not read at
    that station. A system in another region stays unknown."""
    history = PlanetHistory(tmp_path / "h.json")
    assert guilds.region_id(DELTA_SOL) == guilds.region_id(KAYANA) != guilds.region_id(FAR_AWAY)
    assert guilds.region_id(DELTA_SOL) == ", ".join(str(v) for v in galaxy.region(DELTA_SOL))

    history.guilds = guilds.with_record(history.guilds, DELTA_SOL, "merchants", "2026-10-14T10:00:00")
    here = guilds.for_system(history.guilds, DELTA_SOL)
    assert (here["guild"], here["name"], here["inferred"]) == ("merchants", "Merchants Guild", False)
    sibling = guilds.for_system(history.guilds, KAYANA)
    assert (sibling["name"], sibling["inferred"]) == ("Merchants Guild", True)
    assert guilds.for_system(history.guilds, FAR_AWAY) is None

    # The newest answer wins: correcting a mistake must not need a deletion first.
    history.guilds = guilds.with_record(history.guilds, KAYANA, "mercenaries", "2026-10-14T11:00:00")
    assert guilds.for_system(history.guilds, DELTA_SOL)["name"] == "Mercenaries Guild"
    assert guilds.for_system(history.guilds, DELTA_SOL)["inferred"] is True     # read at Kayana now
    assert len(history.guilds) == 1                                            # still one record per region


def test_an_unknown_guild_or_a_damaged_record_is_ignored(tmp_path):
    """Form values and file contents are untrusted: a guild the game has no envoy for changes nothing, and a
    record whose guild is missing or not a string is not shown as an answer."""
    history = PlanetHistory(tmp_path / "h.json")
    assert guilds.with_record(history.guilds, DELTA_SOL, "shopkeepers", "t") == {}
    assert guilds.with_record({}, DELTA_SOL, "", "t") == {}
    region = guilds.region_id(DELTA_SOL)
    assert guilds.for_system({region: {"guild": "nonsense"}}, DELTA_SOL) is None
    assert guilds.for_system({region: "merchants"}, DELTA_SOL) is None
    assert guilds.for_system({}, DELTA_SOL) is None and guilds.for_system(None, DELTA_SOL) is None
    # "No envoy here" is a real answer, not a missing one.
    assert guilds.for_system(guilds.with_record({}, DELTA_SOL, "none", "t"), DELTA_SOL)["name"] == "No envoy here"


def test_the_guilds_survive_a_save_and_load_without_changing_the_file_version(tmp_path):
    """The records are an additive key in planet_history.json: the version stays 2, a file written before the
    feature loads unchanged, and a damaged entry is dropped on load rather than failing the whole file."""
    import json

    path = tmp_path / "h.json"
    history = PlanetHistory(path)
    history.guilds = guilds.with_record({}, DELTA_SOL, "explorers", "2026-10-14T10:00:00")
    history.save()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 2 and raw["guilds"][guilds.region_id(DELTA_SOL)]["guild"] == "explorers"

    again = PlanetHistory(path)
    assert guilds.for_system(again.guilds, DELTA_SOL)["name"] == "Explorers Guild"

    raw["guilds"]["broken"] = ["not a dict"]
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert list(PlanetHistory(path).guilds) == [guilds.region_id(DELTA_SOL)]

    # A file from before the feature (no "guilds" key at all) still loads, with no records.
    del raw["guilds"]
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert PlanetHistory(path).guilds == {}


def test_the_page_shows_the_guild_and_offers_the_form(tmp_path):
    """The system details name the guild (and where it was recorded), the visited-systems table gets a column
    marking an inferred one, and the form offers the three guilds plus "no envoy"."""
    history = PlanetHistory(tmp_path / "h.json")
    history.system_names = {DELTA_SOL: "Delta Sol", KAYANA: "Kayana"}
    ctx = context(history, {DELTA_SOL: {"planets": {}}, KAYANA: {"planets": {}}})
    assert ctx.guild_item(DELTA_SOL)["value"].startswith("not recorded yet")

    history.guilds = guilds.with_record({}, DELTA_SOL, "merchants", "2026-10-14T10:00:00")
    ctx = context(history, {DELTA_SOL: {"planets": {}}, KAYANA: {"planets": {}}})
    assert ctx.guild_item(DELTA_SOL) == {"label": "Guild envoy", "value": "Merchants Guild - recorded here"}
    assert ctx.guild_item(KAYANA)["value"] == "Merchants Guild - recorded in this region, at Delta Sol"
    assert guilds.cell(ctx.guild(DELTA_SOL)) == "Merchants Guild"
    assert guilds.cell(ctx.guild(KAYANA)) == "Merchants Guild (region)"
    assert guilds.cell(ctx.guild(FAR_AWAY)) is None

    sections = planets_view.visited_systems_sections(ctx, DELTA_SOL)
    table = next(s for s in sections if s["type"] == "table")
    column = table["columns"].index("Guild envoy")
    assert sorted(str(r[column]) for r in table["rows"]) == ["Merchants Guild", "Merchants Guild (region)"]
    form = next(s for s in sections if s["type"] == "form")
    assert form["action"] == "set_region_guild" and form["id"] == planets_view.GUILD_FORM_ID
    assert [o["value"] for o in form["fields"][1]["options"]] == ["merchants", "explorers", "mercenaries", "none"]
    assert form["fields"][0]["value"] == planets_view.system_key_text(DELTA_SOL)   # the system shown in the map


def test_recording_a_guild_checks_its_input_and_names_the_region(tmp_path, monkeypatch):
    """The action treats the form's values as untrusted: an unknown system or guild answers ok False and
    writes nothing; a good one is saved to the history file at once and the message names the region."""
    from nms_connector import create_plugin
    from test_connector import FakeCtx

    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    assert plugin._set_guild({"system": "not hex", "guild": "merchants"})["ok"] is False
    assert plugin._set_guild({"system": f"{DELTA_SOL:x}", "guild": "shopkeepers"})["ok"] is False
    assert plugin._set_guild({"system": f"{DELTA_SOL:x}"})["ok"] is False
    assert plugin.history.guilds == {}

    answer = plugin._set_guild({"system": f"{DELTA_SOL:x}", "guild": "mercenaries"})
    assert answer["ok"] is True and answer["focus"] == planets_view.GUILD_FORM_ID
    assert "Mercenaries Guild" in answer["message"] and guilds.region_id(DELTA_SOL) in answer["message"]
    assert guilds.for_system(plugin.history.guilds, KAYANA)["name"] == "Mercenaries Guild"
    assert guilds.for_system(PlanetHistory(plugin.history.path).guilds, DELTA_SOL)["inferred"] is False
