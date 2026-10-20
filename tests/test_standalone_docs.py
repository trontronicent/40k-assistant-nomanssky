"""Documentation invariants for the standalone mode."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_help_has_a_standalone_chapter():
    """`HELP.md` is what the app's manual shows as *Plugin Help*; a mode the user can install must be
    described there, with its own heading so the manual can index it."""
    text = (ROOT / "HELP.md").read_text(encoding="utf-8")
    assert "## Standalone mode" in text
    for topic in ("Ollama", "Updates", "tray", "overlay"):
        assert topic in text, topic


def test_help_has_standalone_troubleshooting():
    """Every feature with a common failure mode gets a troubleshooting entry - the video-memory one above
    all, because a timeout there means VRAM and not a slow model."""
    text = (ROOT / "HELP.md").read_text(encoding="utf-8")
    assert "### Standalone troubleshooting" in text
    assert "video memory" in text


def test_the_changelog_names_the_version_being_built():
    """The release recipe bumps the manifest and the changelog together; a mismatch means a tag would be
    pushed without an entry."""
    version = json.loads((ROOT / "strategicum-plugin.json").read_text(encoding="utf-8"))["version"]
    assert version in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_claude_md_lists_the_standalone_modules():
    """The repo's module map is how the next session finds its way; a package missing from it gets
    re-discovered the hard way."""
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for topic in ("## Standalone mode", "updater", "installer/", "instance.py", "tray.py"):
        assert topic in text, topic


def test_the_manifest_stays_on_the_0_15_0_beta_line():
    """Decided with the user: this plugin stays on `0.15.0-beta.N` until they say otherwise."""
    version = json.loads((ROOT / "strategicum-plugin.json").read_text(encoding="utf-8"))["version"]
    assert version.startswith("0.15.0-beta.")


def test_the_manifest_still_needs_no_newer_app():
    """`app.min_version` moves only when the plugin really needs something a newer app brings - an
    unnecessary bump would stop older apps from installing the plugin at all. Standalone mode itself still
    adds nothing. 3.20.0 is needed for the `glyphs` key (portal addresses drawn as the game's symbols on a
    view cell, a kv/stats item and an overlay area), which older apps would refuse as an unknown key."""
    manifest = json.loads((ROOT / "strategicum-plugin.json").read_text(encoding="utf-8"))
    assert manifest["app"]["min_version"] == "3.20.0"


def test_the_manifest_does_not_declare_the_standalone_files():
    """`contributes` describes what the **app** loads; the standalone host is not an app feature and must
    not appear there, or an older app would refuse the whole manifest."""
    manifest = json.loads((ROOT / "strategicum-plugin.json").read_text(encoding="utf-8"))
    assert set(manifest["contributes"]) == {"backend", "codex"}
    assert manifest["contributes"]["backend"]["module"] == "nms_connector"
