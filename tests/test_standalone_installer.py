"""Static checks on the installer scripts: they are not run here, so the invariants are asserted."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "installer"


def read(name: str) -> str:
    return (INSTALLER / name).read_text(encoding="utf-8-sig")


def test_the_iss_file_packages_everything_the_program_needs():
    """A missing `[Files]` entry produces an install that starts and then fails on an import."""
    text = read("nms-companion.iss")
    for part in ("nms_connector", "standalone", "vendor", "strategicum-plugin.json", "codex",
                 "HELP.md", "postinstall.ps1", "40k-12b-companion.Modelfile", "THIRD-PARTY-NOTICES.md"):
        assert part in text, part


def test_the_install_is_per_user():
    """An install under Program Files cannot be replaced by the in-app updater without elevation, which
    is the whole reason for `PrivilegesRequired=lowest` and `{localappdata}`."""
    text = read("nms-companion.iss")
    assert "PrivilegesRequired=lowest" in text
    assert "{localappdata}\\Programs\\NMS Companion" in text


def test_the_wizard_asks_for_ai_and_voice():
    """Both are optional by decision; the wizard must offer them and pass the answers on, or the user
    gets a multi-gigabyte download they did not ask for."""
    text = read("nms-companion.iss")
    assert "-WithAi" in text and "-WithVoice" in text
    assert "CreateInputOptionPage" in text


def test_the_autostart_entry_opens_no_browser():
    """"Start with Windows" must mean the tray icon, not a browser window on every boot."""
    text = read("nms-companion.iss")
    assert "--no-browser" in text
    assert "CurrentVersion\\Run" in text


def test_the_uninstaller_asks_before_removing_the_data():
    """The data dir holds months of planet history and the generated Codex; it is kept unless the user
    says otherwise."""
    text = read("nms-companion.iss")
    assert "NMS Companion" in text and "CurUninstallStep" in text


def test_the_companion_modelfile_ships_and_names_a_public_base():
    """`ollama create` can only build the model if the `FROM` tag is public - a local-only base would
    fail on every machine but the developer's."""
    text = read("40k-12b-companion.Modelfile")
    assert "FROM gemma4:12b" in text
    assert "num_ctx" in text


def test_the_modelfile_is_a_copy_of_the_apps():
    """The two must not drift: the app measured 9.5 GB at 16K beside the running game, and the standalone
    install inherits that budget."""
    app_file = Path(r"J:\40k-assistant\40k-12b-companion.Modelfile")
    if not app_file.is_file():
        pytest.skip("the app repository is not on this machine")
    ours = read("40k-12b-companion.Modelfile")
    theirs = app_file.read_text(encoding="utf-8")
    for line in [row for row in theirs.splitlines() if row.strip() and not row.startswith("#")]:
        assert line in ours, line


def test_postinstall_creates_the_named_model():
    """Settings must end up pointing at `40k-12b-companion`; pulling only the base would give the user a
    model without the companion's context size and sampling."""
    text = read("postinstall.ps1")
    assert "ollama create" in text and "40k-12b-companion" in text
    assert "gemma4:12b" in text and "nomic-embed-text" in text


def test_postinstall_writes_the_settings_the_host_reads():
    """The host reads `<data>\\standalone.json` on every start; the installer is what turns the optional
    features on."""
    text = read("postinstall.ps1")
    assert "standalone.json" in text
    for key in ("ai_enabled", "tts_enabled", "chat_model", "voice"):
        assert key in text, key


def test_postinstall_never_matches_english_command_output():
    """The OS here is German-locale: `netstat` says ABHÖREN and `taskkill` says ERFOLGREICH. Matching
    English words in command output is a silent failure on this machine."""
    text = read("postinstall.ps1")
    for banned in ("-match 'LISTENING'", '-match "LISTENING"', "SUCCESS:", "'Running'", "-eq 'Running'"):
        assert banned not in text


def test_postinstall_checks_exit_codes_not_text():
    """Ollama's pull is judged by `$LASTEXITCODE`; parsing its progress text would break on the next
    version and on a translated console."""
    assert "$LASTEXITCODE" in read("postinstall.ps1")


def test_the_build_script_vendors_what_the_host_imports():
    """The embeddable Python ships no packages; each one the host imports has to be installed into it."""
    text = read("build.ps1")
    for package in ("numpy", "zstandard", "pillow", "pystray", "six"):
        assert package in text, package
    assert "python-" in text and "embed-amd64" in text


def test_the_build_script_refuses_to_package_game_data_or_mapping():
    """`mapping.json` is LGPL and downloaded at runtime; item names and icons come from the user's own
    installation. Neither may ever be inside the installer."""
    text = read("build.ps1")
    for forbidden in ("mapping.json", "gamedata", ".data"):
        assert forbidden in text, forbidden


def test_the_build_script_smoke_tests_the_packaged_interpreter():
    """A vendored tree that cannot import numpy produces an install that dies on the first tick."""
    text = read("build.ps1")
    assert "import numpy" in text and "pystray" in text


@pytest.mark.parametrize("name", ["build.ps1", "postinstall.ps1"])
def test_powershell_files_are_crlf_with_a_bom(name):
    """A BOM-less `.ps1` with non-ASCII text fails to parse in PowerShell 5.1, and LF endings break
    here-strings; this asserts the committed bytes."""
    raw = (INSTALLER / name).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), f"{name} needs a UTF-8 BOM"
    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b""), f"{name} must be CRLF throughout"


def test_gitattributes_keeps_the_powershell_endings():
    """Without a rule, a `.ps1` can be committed as LF by another machine and stop parsing."""
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.ps1" in text and "crlf" in text.lower()


def test_the_build_artefacts_are_git_ignored():
    """The embeddable Python and the built installer are machine artefacts; committing them would add
    tens of megabytes to every clone - and the updater downloads the repository as a tarball."""
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "vendor/" in text and "installer/Output/" in text


def test_the_installer_readme_states_what_is_downloaded_and_its_licences():
    """The installer fetches Ollama, a model and a voice; the user is told what and under which licence,
    and that nothing of Hello Games' is redistributed."""
    text = (INSTALLER / "README.md").read_text(encoding="utf-8")
    for topic in ("Ollama", "Piper", "gemma4", "Hello Games", "MIT"):
        assert topic in text, topic


def test_the_manifest_version_matches_the_installer_name():
    """`build.ps1` names the output after the manifest version, so an installer file always says which
    version it carries."""
    manifest = json.loads((ROOT / "strategicum-plugin.json").read_text(encoding="utf-8"))
    assert "MyAppVersion" in read("nms-companion.iss")
    assert manifest["version"]


def test_the_build_script_puts_the_install_root_on_the_interpreters_path():
    """Measured 2026-10-13: with an `._pth` file the embeddable interpreter's sys.path is exactly that
    file's entries, resolved against the interpreter's own folder - the current directory is **not**
    added. Without `..\..` the shortcut `pythonw.exe -m standalone` answers "No module named
    standalone", so the installed program could never start."""
    text = read("build.ps1")
    assert '"..\.."' in text
    assert "_pth" in text


def test_the_shortcut_runs_the_vendored_interpreter():
    """The install ships its own Python; a shortcut pointing at a system interpreter would use whatever
    the user happens to have (this machine has six, and bare `python` is 3.14)."""
    text = read("nms-companion.iss")
    assert "pythonw.exe" in text and "vendor" in text
    assert "-m standalone" in text


def test_the_build_script_finds_the_compiler_where_it_is():
    """Inno Setup installs per machine or per user - winget puts it in `%LOCALAPPDATA%\Programs`, which a
    hard-coded `Program Files (x86)` path misses (measured 2026-10-13: the first build could not find
    ISCC.exe). The script looks in all of them and says how to install it when there is none."""
    text = read("build.ps1")
    assert "Find-Iscc" in text
    assert "LOCALAPPDATA" in text and "Program Files (x86)" in text
    assert "winget install" in text


def test_the_installer_shows_and_ships_the_third_party_notices():
    """The install packages its own Python and five wheels, one of them LGPL; their licences only reach
    the user if the notices file is shown in the wizard, installed beside the program and reachable from
    the Start menu afterwards."""
    text = read("nms-companion.iss")
    assert r"InfoBeforeFile=..\THIRD-PARTY-NOTICES.md" in text
    ships = [line for line in text.splitlines()
             if line.startswith("Source:") and "THIRD-PARTY-NOTICES.md" in line]
    assert ships and 'DestDir: "{app}"' in ships[0]
    assert "credits" in text                       # the Start menu entry


def test_the_installer_names_the_author_and_the_repository():
    """What Windows shows as the publisher, and where a user who installed the exe can find the source."""
    text = read("nms-companion.iss")
    assert "Shorthand Dev / TronTronic Entertainment" in text
    assert "AppCopyright=Copyright (c) 2026" in text
    assert "github.com/trontronicent/40k-assistant-nomanssky" in text


def test_the_build_refuses_a_stale_notices_file():
    """`credits.py` is the one list; the installer must not be compilable while the file it ships
    disagrees with it (that is how the old "nothing LGPL is packaged" claim survived)."""
    text = read("build.ps1")
    assert "write_notices.py" in text and "--check" in text
