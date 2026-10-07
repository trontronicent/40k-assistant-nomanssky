"""Error handling: a failure in one part must cost only that part, be logged once, and be visible to the user and the
persona (logs.py, GameTables._guard, the tick stages, optional save sections, the persona's data blocks)."""

import asyncio
import json
import logging

import pytest

from nms_connector import logs, tables
from nms_connector.gamedata import GameData
from nms_connector.store import TableStore
from test_connector import FakeCtx, create_plugin


@pytest.fixture(autouse=True)
def fresh_log_memory():
    """Each test starts with an empty 'already logged' memory and the default logger."""
    logs.reset()
    yield
    logs.reset()


def test_a_missing_file_is_silent_but_an_unreadable_one_warns_once(tmp_path, caplog):
    """read_json returns None for both, but only a damaged file is a warning (naming file and reason), and the same
    problem seen again at the next poll is not logged again within the repeat window."""
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"a": 1}), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text("{ nope", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="vox-core.plugin.nomanssky"):
        assert logs.read_json(good, "x") == {"a": 1}
        assert logs.read_json(tmp_path / "missing.json", "x") is None
        assert not caplog.records
        assert logs.read_json(bad, "The test file") is None and logs.read_json(bad, "The test file") is None
    assert len(caplog.records) == 1
    assert "The test file" in caplog.text and "bad.json" in caplog.text and "JSONDecodeError" in caplog.text


def test_warn_once_repeats_only_after_the_window():
    """The same key is logged again after REPEAT_S seconds, a different key at once - a failure that persists is
    reported again and again slowly, not every 5 s."""
    assert logs.warn_once("k", "first", now=1000.0)
    assert not logs.warn_once("k", "again", now=1000.0 + logs.REPEAT_S - 1)
    assert logs.warn_once("k", "later", now=1000.0 + logs.REPEAT_S + 1)
    assert logs.warn_once("other", "different problem", now=1000.0)


def test_a_damaged_item_cache_and_table_store_are_reported_and_ignored(tmp_path, caplog):
    """A corrupt gamedata/items.json or tables.json used to be dropped without a word; now each is a warning and the
    plugin rebuilds from the game files / falls back as before."""
    data = GameData(tmp_path)
    data.cache_file.parent.mkdir(parents=True)
    data.cache_file.write_text("garbage", encoding="utf-8")
    store = TableStore(tmp_path)
    store.file.write_text("[1,", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="vox-core.plugin.nomanssky"):
        assert data.load_stored() is False and store.load() is None
    assert "The item database cache" in caplog.text and "The stored game tables" in caplog.text


def test_an_unwritable_store_is_a_warning_not_an_exception(tmp_path, caplog):
    """A disk problem while writing tables.json (here: its folder is a file) returns False and warns; the tables stay
    in memory and the persona is not affected."""
    blocker = tmp_path / "gamedata"
    blocker.write_text("i am a file", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="vox-core.plugin.nomanssky"):
        assert TableStore(tmp_path).save("1", "english", {}, {}) is False
    assert "could not be written" in caplog.text


def test_one_failing_game_table_falls_back_and_the_others_are_still_read(monkeypatch, tmp_path, caplog):
    """If one table parser raises something unexpected, that table keeps its built-in values and is named in the
    warnings, the other tables load, and nothing is raised - before, the exception stopped the whole load and the
    game files were retried every poll."""
    from nms_connector import ships, timers

    def boom(install):
        raise KeyError("layout moved")
    monkeypatch.setattr(timers, "load_tables", boom)
    t = tables.GameTables()
    with caplog.at_level(logging.WARNING, logger="vox-core.plugin.nomanssky"):
        warnings = t.load(object())
    assert t.loaded and t.timer_durations is timers.FALLBACK        # the error-only dict is not used as durations
    assert any("Timer durations" in w and "layout moved" in w for w in warnings)
    assert "timers could not be read" in caplog.text and t.ship_ranges is not None and ships.FALLBACK


def _plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    return create_plugin(FakeCtx(tmp_path / "data"))


def test_a_failing_stage_does_not_stop_the_other_stages(tmp_path, monkeypatch, caplog):
    """A tick runs mapping, game files, save and memory as independent stages: when the game-file stage raises, the
    save and memory stages still run, the error is shown (plugin.error), logged once, and the tick does not raise."""
    plugin = _plugin(tmp_path, monkeypatch)
    ran = []

    async def failing():
        raise RuntimeError("tables exploded")

    async def ok_saves():
        ran.append("save")

    async def ok_memory(force=False):
        ran.append("memory")

    async def ok_mapping(force=False):
        ran.append("mapping")
    plugin._ensure_mapping, plugin._ensure_gamedata, plugin._tick_saves, plugin._read_memory = ok_mapping, failing, ok_saves, ok_memory
    with caplog.at_level(logging.WARNING, logger="test.nms"):
        asyncio.run(plugin._tick())
        asyncio.run(plugin._tick())
    assert ran == ["mapping", "save", "memory"] * 2
    assert plugin.error == "game files: RuntimeError: tables exploded"
    assert caplog.text.count("The game files step failed") == 1       # the second identical failure is not logged again
    asyncio.run(plugin._tick())
    ok_game = plugin._ensure_gamedata

    async def fine():
        return None
    plugin._ensure_gamedata = fine
    asyncio.run(plugin._tick())
    assert plugin.error is None and ok_game


def test_a_broken_optional_part_of_a_save_is_left_out_and_shown(tmp_path, monkeypatch):
    """When reading the ships (or any other optional section) of a save fails, the other sections are still read, the
    section is empty, `degraded` names it with the reason and the page shows a warning notice - the save is not lost."""
    from nms_connector import ships
    plugin = _plugin(tmp_path, monkeypatch)
    monkeypatch.setattr(ships, "ships_from_save", lambda save: (_ for _ in ()).throw(KeyError("Inventory")))
    assert plugin._extract("ships", [], ships.ships_from_save, {}) == []
    assert plugin.degraded == {"ships": "KeyError: 'Inventory'"}
    notices = plugin.page.notices()
    assert any(n["level"] == "warn" and "ships (KeyError: 'Inventory')" in n["text"] for n in notices)
    assert plugin._extract("ships", [], lambda: ["fine"]) == ["fine"] and plugin.degraded == {}


def test_a_failing_block_costs_only_that_block_of_the_persona_data(tmp_path, monkeypatch, caplog):
    """If the cooking block raises, the rest of the persona data is still built and says the cooking block is
    unavailable (so the model does not invent it); if the whole build raises, the persona gets a block that says the
    data is unavailable instead of nothing."""
    plugin = _plugin(tmp_path, monkeypatch)
    plugin.snapshot = {"location": {"galaxy": "Euclid", "portal": "0001"}, "bases": [], "units": 0, "nanites": 0,
                       "quicksilver": 0, "freighter": {"name": None}, "ships": [], "storage": [], "current_mission": None,
                       "saved_at": None, "exosuit": [], "exosuit_cargo": []}
    companion = plugin.companion

    def boom(*args):
        raise ValueError("bad recipe")
    monkeypatch.setattr(companion, "cooking_lines", boom)
    with caplog.at_level(logging.WARNING, logger="test.nms"):
        text = companion.chat_context("How do I cook a stew?")["text"]
    assert "cooking could not be built right now: ValueError: bad recipe" in text
    assert "The cooking of the persona data failed" in caplog.text

    monkeypatch.setattr(companion, "_chat_context", boom)
    whole = companion.chat_context("anything")
    assert "could not be built right now (ValueError: bad recipe)" in whole["text"] and "do not guess" in whole["text"]
    assert whole["instructions"] == [] and whole["single_context"] is False
