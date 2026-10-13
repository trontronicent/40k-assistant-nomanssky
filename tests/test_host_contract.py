"""The contract both hosts implement.

These tests are the enforcement of the "two hosts, one codebase" rule in CLAUDE.md: they fail when a
change serves only the app's plugin system or only the standalone host.
"""
import inspect
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONNECTOR = ROOT / "nms_connector"
HOST = ROOT / "standalone"

# What a host must call. The app calls exactly these (plugins/loader.py, plugins/personas.py,
# plugins/overlay.py, plugins/item_icons.py); the standalone host calls no more and no less.
HOST_SURFACE = ("start", "stop", "view", "action", "personas", "chat_context", "overlay", "item_icons")


def test_the_connector_never_imports_the_standalone_host():
    """The connector must run inside the app with no `standalone` package present at all. One import
    would make the app's loader fail at import time, which the app reports as a dead plugin."""
    for path in CONNECTOR.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not re.search(r"^\s*(from|import)\s+standalone\b", text, re.M), path


def test_the_standalone_host_uses_only_public_connector_methods():
    """The host reaches the connector through its public methods, as `code-shape.md` requires of every
    module here. Touching a `_private` field couples the host to internals the app does not use, and the
    two hosts then drift apart."""
    for path in HOST.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not re.search(r"\b(plugin|connector)\._[a-z]", text), path


def test_the_connector_offers_every_method_a_host_calls():
    """A renamed or removed method breaks whichever host was not being tested at the time; the surface is
    asserted in one place instead."""
    from nms_connector.plugin import NmsConnector
    for name in HOST_SURFACE:
        assert callable(getattr(NmsConnector, name, None)), name


def test_the_standalone_host_calls_nothing_else_on_the_connector():
    """The other direction: a host that reached for a method the app never calls would be relying on
    something the app's contract does not cover."""
    allowed = set(HOST_SURFACE) | {"item_icons"}
    pattern = re.compile(r"\b(?:deps\.)?plugin\.([a-z_]+)\s*\(")
    for path in HOST.rglob("*.py"):
        for name in pattern.findall(path.read_text(encoding="utf-8", errors="replace")):
            assert name in allowed, f"{path.name} calls plugin.{name}()"


def test_the_connector_runs_against_both_contexts(tmp_path, monkeypatch):
    """The same connector, built twice: once on the standalone context, once on a stand-in for the app's
    `PluginContext`. Both must answer the same shapes - this is the test that catches a feature wired
    into only one host."""
    import asyncio

    from nms_connector import create_plugin
    from standalone.context import StandaloneContext

    class FakeAppContext(StandaloneContext):
        """The app's context carries the same attributes; subclassing keeps the two in step on purpose."""

    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "no-saves"))
    answers = []
    for index, factory in enumerate((StandaloneContext, FakeAppContext)):
        ctx = factory("nomanssky", "0.0.0", ROOT, tmp_path / f"data{index}")
        plugin = create_plugin(ctx)
        answers.append({
            "view": sorted(plugin.view().keys()),
            "personas": [persona["slug"] for persona in plugin.personas()],
            "context": sorted(plugin.chat_context("where am i").keys()),
            "overlay": sorted(plugin.overlay().keys()),
            "icons": isinstance(plugin.item_icons(), dict),
        })
        asyncio.run(plugin.stop())
    assert answers[0] == answers[1]
    assert answers[0]["personas"] == ["companion"]


def test_the_standalone_app_version_covers_the_manifests_minimum():
    """`app.min_version` says which host features the connector needs. The standalone host declares the
    version it implements; if the manifest asks for more, the host is behind and must catch up in the
    same change."""
    from standalone.context import APP_VERSION
    from standalone.updater import version_key
    manifest = json.loads((ROOT / "strategicum-plugin.json").read_text(encoding="utf-8"))
    assert version_key(APP_VERSION) >= version_key(manifest["app"]["min_version"])


def test_section_types_match_the_renderer():
    """`ctx.section_types` is what the connector believes it may send. A type advertised but not drawn is
    a blank gap in the page; a type drawn but not advertised makes the connector fall back needlessly."""
    from standalone.context import SECTION_TYPES
    js = (HOST / "web" / "sections.js").read_text(encoding="utf-8")
    block = re.search(r"const BUILDERS = \{(.*?)\n\};", js, re.S).group(1)
    drawn = set(re.findall(r"(?m)^\s*([a-z]+):", block))
    assert drawn == set(SECTION_TYPES)


def test_every_chat_context_key_is_handled_somewhere():
    """`chat_context()` may return title, text, instructions, single_context and recipes. A key no host
    code mentions is data the connector computes and the standalone user never sees."""
    handled = (HOST / "chat.py").read_text(encoding="utf-8") + \
              (HOST / "web" / "chat.js").read_text(encoding="utf-8")
    for key in ("title", "text", "instructions", "single_context", "recipes"):
        assert key in handled, key


def test_every_overlay_key_is_handled():
    """The connector's `overlay()` sends areas, timers, lines, its persona, the codeword, toggles and the
    Codex-search opt-in. The standalone side must account for each or silently drop features."""
    text = (HOST / "overlay.py").read_text(encoding="utf-8") + (HOST / "alerts.py").read_text(encoding="utf-8")
    for key in ("areas", "timers", "lines", "default_on"):
        assert key in text, key
    # The remaining keys are the page's and the tray's business; they are accounted for there.
    page = (HOST / "web" / "panels.js").read_text(encoding="utf-8") + (HOST / "tray.py").read_text(encoding="utf-8")
    for key in ("codex", "persona"):
        assert key in (text + page).lower(), key


def test_the_codex_write_signature_matches_the_connectors_call():
    """`plugin.py` calls `ctx.codex.write(docs, owner=..., adopt=..., adopt_dirs=...)` and
    `codex_sync.describe` reads the result. A channel with a different signature or return shape fails
    only at runtime, after 2,400 documents have been prepared."""
    from standalone.codex import COUNT_KEYS, StandaloneCodex
    parameters = inspect.signature(StandaloneCodex.write).parameters
    for name in ("documents", "owner", "adopt", "adopt_dirs"):
        assert name in parameters, name
    described = (CONNECTOR / "codex_sync.py").read_text(encoding="utf-8")
    for key in re.findall(r"counts\.get\(['\"]([a-z_]+)['\"]", described):
        assert key in COUNT_KEYS, key


def test_the_data_version_is_known_to_the_updater():
    """The manifest's `data_version` is what the standalone downgrade check compares against; a raise
    must be visible to both hosts."""
    manifest = json.loads((ROOT / "strategicum-plugin.json").read_text(encoding="utf-8"))
    from standalone import updater
    assert "data_version" in inspect.getsource(updater.check_data_version)
    assert isinstance(manifest.get("data_version"), int)


def test_claude_md_carries_the_two_hosts_rule():
    """The rule has to be where the next session reads it, not only in the plan - that is how every other
    hard-won invariant in this repository survives."""
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "two hosts" in text.lower()
    assert "standalone" in text.lower()
    for topic in ("SECTION_TYPES", "APP_VERSION", "data_version"):
        assert topic in text, topic
