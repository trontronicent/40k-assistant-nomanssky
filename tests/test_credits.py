"""The credits: one list in `nms_connector/credits.py`, repeated in the manifest, the notices file and the
page's About tab. These tests are what stops the four from drifting apart - the usual way a credit gets
added for one host and is missing in the other."""
import json
import sys
from pathlib import Path

import pytest

from nms_connector import credits

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import write_notices  # noqa: E402  (after the path set-up)


def manifest() -> dict:
    return json.loads((ROOT / "strategicum-plugin.json").read_text(encoding="utf-8"))


def test_the_generated_files_are_up_to_date():
    """`--check` is what `installer/build.ps1` runs before compiling; failing here means somebody edited
    credits.py and did not run `python tools/write_notices.py`, so the installer would ship a notices
    file that disagrees with the About tab."""
    assert write_notices.main(["--check"]) == 0


def test_the_author_is_named_the_same_everywhere():
    """One spelling of the author, or the installer, the manual and the page each claim a different
    maker. The name is the user's decision (CLAUDE.md), so it is asserted, not guessed."""
    assert credits.AUTHOR == "Reto Kummer alias Reat Kay, Shorthand Dev / TronTronic Entertainment"
    assert manifest()["author"]["name"] == credits.AUTHOR
    for name in ("LICENSE", "README.md", "HELP.md", "THIRD-PARTY-NOTICES.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert credits.AUTHOR in text, name
    iss = (ROOT / "installer" / "nms-companion.iss").read_text(encoding="utf-8-sig")
    assert f"AppPublisher={credits.AUTHOR}" in iss


def test_the_repository_url_is_named_wherever_the_author_is():
    """A credit without a way back to the source is half a credit; the user asked for the repository URL
    in the repository, the installer and the UI."""
    assert credits.REPO_URL in (ROOT / "README.md").read_text(encoding="utf-8")
    assert credits.REPO_URL in (ROOT / "HELP.md").read_text(encoding="utf-8")
    assert credits.REPO_URL in (ROOT / "installer" / "nms-companion.iss").read_text(encoding="utf-8-sig")
    facts = credits.sections("1.2.3")[0]
    assert any(item["value"] == credits.REPO_URL for item in facts["items"])


def test_everything_the_installer_packages_is_credited():
    """The wheels in `installer/build.ps1`'s pip line are *shipped*, so each one's licence applies to our
    distribution. A wheel added there and not here would ship uncredited - which is how the script's own
    comment came to claim that nothing LGPL was packaged while pystray was."""
    build = (ROOT / "installer" / "build.ps1").read_text(encoding="utf-8-sig")
    line = next(ln for ln in build.splitlines() if "--target" in ln)
    packaged = line.split("site-packages\")")[1].split()
    assert packaged, "the pip line in build.ps1 no longer names its packages"
    names = " ".join(entry.name.lower() for entry in credits.BUNDLED.entries)
    for wheel in packaged:
        assert wheel.lower().rstrip('`') in names, wheel


def test_the_lgpl_dependency_is_named_as_such():
    """pystray is the one bundled library whose licence asks for more than a line of thanks, so the
    notices must say it is LGPL, unmodified and replaceable - not merely list it."""
    notices = (ROOT / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    assert "pystray" in notices and "LGPL-3.0" in notices
    entry = next(e for e in credits.BUNDLED.entries if e.name == "pystray")
    assert "unmodified" in entry.what


def test_the_manifest_credits_pass_the_app_s_own_limits():
    """The app rejects a manifest with more than 30 credits, a name over 80 characters or a `for` over
    200, and a rejected entry is dropped silently from the manual - so the limits are checked here, where
    the app is not importable."""
    entries = manifest()["credits"]
    assert 1 < len(entries) <= 30
    for entry in entries:
        assert set(entry) <= {"name", "for", "url"}
        assert entry["name"].strip() and len(entry["name"]) <= 80, entry["name"]
        assert len(entry.get("for", "")) <= 200, entry["name"]
        assert entry.get("url", "https://").startswith("https://"), entry["name"]


def test_every_credit_carries_a_licence_and_what_it_gave():
    """A name on its own is not a credit: the reader has to see what the work did here and under which
    licence, which is exactly what the About tab's columns show."""
    for group in credits.GROUPS:
        assert group.entries, group.title
        for entry in group.entries:
            assert entry.name.strip() and entry.what.strip() and entry.license.strip(), entry.name
            assert entry.url == "" or entry.url.startswith("https://"), entry.name


@pytest.mark.parametrize("host", ["plugin", "standalone"])
def test_the_about_tab_uses_only_section_types_both_hosts_draw(host):
    """The About tab is built by the connector so that both hosts show the identical credits; a type the
    standalone page cannot draw would leave a blank gap there (the two-hosts rule in CLAUDE.md)."""
    from standalone.context import SECTION_TYPES
    sections = credits.sections("1.2.3", host)
    assert sections, "the About tab must not be empty"
    for section in sections:
        assert section["type"] in SECTION_TYPES, section["type"]
        assert section["type"] in {"kv", "table", "text"}, section["type"]


def test_the_about_tab_names_the_host_it_runs_in():
    """The one line that may legitimately differ between the two hosts: which one the user is looking at.
    It tells a bug report whether the plugin or the standalone companion is meant."""
    plugin = json.dumps(credits.sections("1.2.3", "plugin"))
    standalone = json.dumps(credits.sections("1.2.3", "standalone"))
    assert "a plugin in the 40k Assistant" in plugin
    assert "the standalone companion" in standalone
    assert plugin.replace("a plugin in the 40k Assistant", "the standalone companion") == standalone


def test_every_credited_work_reaches_the_about_tab():
    """The tab is the credit the user actually sees. A group added to the module but left out of
    `sections()` would be credited in files nobody opens."""
    rendered = json.dumps(credits.sections("1.2.3"), ensure_ascii=False)
    for group in credits.GROUPS:
        assert group.title in rendered, group.title
        for entry in group.entries:
            assert entry.name in rendered, entry.name
            assert entry.license in rendered, entry.license
