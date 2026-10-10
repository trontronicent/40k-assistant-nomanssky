"""When and how the plugin's generated documents are written through the app's Codex channel (codex_sync.py)."""
import asyncio
from types import SimpleNamespace

import pytest

from nms_connector import codex_sync, game_terms, worlds
from test_connector import FakeCtx, create_plugin
from test_recipes import ITEMS, RecordingChannel, book

INSTALL = SimpleNamespace(build_id="25732212", language="german")


def test_the_stamp_names_what_the_documents_depend_on():
    """A write is due again after a game update (build), a language change or a new plugin version, and for
    nothing else - otherwise a 2,400-document write would repeat on every 5 s tick."""
    assert codex_sync.stamp_of(INSTALL, "0.15.0") == {"build": "25732212", "language": "german", "version": "0.15.0"}
    assert codex_sync.stamp_of(None, "0.15.0") == {"build": None, "language": None, "version": "0.15.0"}


def test_a_write_is_due_once_per_stamp_and_cools_down_after_a_failure(tmp_path):
    """due() is true until the stamp has been remembered, false for the same stamp afterwards, true again for a
    new one, and false for RETRY_AFTER_S after a failed write (then retried). The remembered stamp survives a
    restart, so the app's start does not rewrite everything."""
    publisher = codex_sync.CodexPublisher(tmp_path)
    stamp = codex_sync.stamp_of(INSTALL, "0.15.0")
    assert publisher.due(stamp, 1000.0)
    publisher.failed(1000.0)
    assert not publisher.due(stamp, 1000.0 + codex_sync.RETRY_AFTER_S - 1)
    assert publisher.due(stamp, 1000.0 + codex_sync.RETRY_AFTER_S + 1)
    publisher.remember(stamp)
    assert not publisher.due(stamp, 5000.0) and publisher.failed_at is None
    assert not codex_sync.CodexPublisher(tmp_path).due(stamp, 5000.0), "survives a restart"
    assert publisher.due(codex_sync.stamp_of(INSTALL, "0.15.1"), 5000.0)
    assert publisher.due(codex_sync.stamp_of(SimpleNamespace(build_id="26000000", language="german"), "0.15.0"), 5000.0)


def test_a_damaged_stamp_file_just_means_a_write_is_due(tmp_path):
    """An unreadable stamp is treated as 'nothing written yet': one extra, harmless write, never an error."""
    (tmp_path / codex_sync.STAMP_NAME).write_text("{not json", encoding="utf-8")
    assert codex_sync.CodexPublisher(tmp_path).due(codex_sync.stamp_of(INSTALL, "0.15.0"), 1.0)


def test_the_result_line_names_what_was_kept_and_what_was_left_out():
    """The page line always has written/unchanged, and mentions documents removed, kept because the user edited
    them, or left out because the user deleted them - so a number that does not add up is explained."""
    plain = codex_sync.describe({"library": "No Man's Sky", "written": 3, "unchanged": 2397})
    assert plain == "Codex documents in the library 'No Man's Sky': 3 written, 2,397 unchanged."
    full = codex_sync.describe({"library": "L", "written": 1, "unchanged": 0, "removed": 2, "kept_edited": 4, "hidden": 5})
    assert "2 removed" in full and "4 kept because you edited them" in full and "5 left out because you deleted them" in full


@pytest.fixture
def ready_plugin(tmp_path, monkeypatch):
    """A connector whose game tables are 'loaded' and whose app channel is a recording stand-in."""
    from nms_connector.tables import GameTables  # noqa: F401 - the plugin builds its own
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    ctx = FakeCtx(tmp_path / "data")
    ctx.codex = RecordingChannel()
    plugin = create_plugin(ctx)
    plugin.install = INSTALL
    plugin.tables.loaded = True
    plugin.tables.recipes = book()
    plugin.tables.terms = game_terms.GameTerms(language="german")
    plugin.tables.worlds = worlds.WorldBook.from_texts({"DEAD9": "Airless %PLANETCLASS%"}, {"DEAD9": "Stickiger %PLANETCLASS%"}, "german")
    plugin.gamedata.items = dict(ITEMS)
    return plugin, ctx


def test_the_work_loop_writes_the_documents_once_per_build(ready_plugin):
    """The stage writes when the tables are ready and a write is due, remembers the stamp, and is silent on the
    next ticks. A new plugin version (a new stamp) writes again."""
    plugin, ctx = ready_plugin
    asyncio.run(plugin._publish_codex())
    assert len(ctx.codex.calls) == 1
    asyncio.run(plugin._publish_codex())
    asyncio.run(plugin._publish_codex())
    assert len(ctx.codex.calls) == 1, "nothing is due until the build or the version changes"
    ctx.version = "0.15.1"
    asyncio.run(plugin._publish_codex())
    assert len(ctx.codex.calls) == 2


def test_the_stage_waits_for_the_tables_and_skips_an_app_without_the_channel(ready_plugin):
    """Before the game files are read, or on an app without ctx.codex, the stage does nothing at all (no error
    and no write attempt) - a plugin on an older app must not fail every tick."""
    plugin, ctx = ready_plugin
    plugin.tables.loaded = False
    asyncio.run(plugin._publish_codex())
    assert ctx.codex.calls == []
    plugin.tables.loaded = True
    saved, ctx.codex = ctx.codex, None
    asyncio.run(plugin._publish_codex())
    assert saved.calls == []


def test_a_refused_write_is_reported_and_retried_later_not_every_tick(ready_plugin):
    """When the channel refuses the request, the stage raises (the page shows it), the failure time is set so
    the write is not retried on the next tick, and the stamp is NOT remembered - so it is tried again later."""
    plugin, ctx = ready_plugin

    class Refusing:
        async def write(self, docs, owner="default", adopt=None, adopt_dirs=()):
            raise RuntimeError("document 'x' is too big")

    ctx.codex = Refusing()
    with pytest.raises(RuntimeError, match="too big"):
        asyncio.run(plugin._publish_codex())
    assert plugin.codex_publisher.failed_at is not None
    asyncio.run(plugin._publish_codex())             # cooling down: silent, no second attempt
    ctx.codex = RecordingChannel()
    asyncio.run(plugin._publish_codex())
    assert ctx.codex.calls == [], "still inside the cool-down"
