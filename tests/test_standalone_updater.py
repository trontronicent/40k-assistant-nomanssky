"""The updater: tag parsing, channels, download verification, the swap and the rollback."""
import io
import json
import tarfile
from pathlib import Path

import pytest

from standalone import updater


def test_tags_are_parsed_newest_first():
    """The Updates page lists versions; a wrong order offers an old release as the newest one."""
    tags = ["v0.14.1", "v0.15.0-beta.2", "v0.9.0", "not-a-tag", "v0.15.0"]
    assert updater.parse_tags(tags)[:3] == ["0.15.0", "0.15.0-beta.2", "0.14.1"]


def test_a_prerelease_is_recognised():
    """The channel decides what is offered; a SemVer suffix marks a pre-release, as in the app 3.16.0."""
    assert updater.is_prerelease("0.15.0-beta.2") is True
    assert updater.is_prerelease("0.15.0") is False


def test_beta_numbers_sort_numerically():
    """`beta.10` is newer than `beta.2`; comparing the suffixes as text would offer beta.2 as the
    newest, which is exactly the version line this plugin is on."""
    assert updater.parse_tags(["v0.15.0-beta.2", "v0.15.0-beta.10"])[0] == "0.15.0-beta.10"


def test_the_stable_channel_hides_pre_releases():
    """A user on stable must not be offered a beta, and the installed beta must still be listed so they
    can see what they are running."""
    versions = updater.offered(["0.16.0-beta.1", "0.15.0", "0.14.1"], channel="stable",
                               installed="0.15.0")
    assert versions == ["0.15.0", "0.14.1"]


def test_the_pre_release_channel_offers_everything():
    """This plugin ships on the beta line, so the default channel must show the betas."""
    versions = updater.offered(["0.16.0-beta.1", "0.15.0"], channel="pre-release", installed="0.15.0")
    assert versions == ["0.16.0-beta.1", "0.15.0"]


def test_an_installed_beta_stays_visible_on_stable():
    """Otherwise the Updates page would not show what is running at all."""
    versions = updater.offered(["0.15.0-beta.3", "0.14.1"], channel="stable", installed="0.15.0-beta.3")
    assert "0.15.0-beta.3" in versions


def test_each_version_is_labelled_update_or_downgrade():
    """Downgrading is a first-class choice here (a game update can break a newer release), so the page
    must say which direction a version is. These are all above the standalone floor; the blocked case
    has its own test."""
    rows = updater.rows(["0.17.0", "0.16.0", "0.15.0-beta.3"], installed="0.16.0")
    assert [row["action"] for row in rows] == ["update", "installed", "downgrade"]


def test_a_tarball_is_extracted_without_escaping_the_staging_dir(tmp_path):
    """A tarball is untrusted data. An entry with `..` must be refused rather than written next to the
    installed program."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("../evil.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(updater.UpdateError):
        updater.extract(buffer.getvalue(), tmp_path / "staging")


def test_a_tarball_with_a_link_is_refused(tmp_path):
    """A symlink could point anywhere on the disk; the app's manifest check refuses them too."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("repo/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    with pytest.raises(updater.UpdateError):
        updater.extract(buffer.getvalue(), tmp_path / "staging")


def _tarball(files: dict) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, text in files.items():
            raw = text.encode("utf-8")
            info = tarfile.TarInfo("repo-0.15.0/" + name)
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))
    return buffer.getvalue()


def test_a_good_tarball_extracts_to_its_single_top_folder(tmp_path):
    """GitHub wraps everything in one folder; the updater strips it so the code lands where it belongs."""
    data = _tarball({"strategicum-plugin.json": "{}", "nms_connector/__init__.py": "x"})
    root = updater.extract(data, tmp_path / "staging")
    assert (root / "nms_connector" / "__init__.py").is_file()


def test_a_download_whose_manifest_disagrees_is_refused(tmp_path):
    """The tag says 0.15.0; a tarball whose manifest says something else means the tag moved or the
    download is wrong, and the app refuses exactly this (502 on a moved tag)."""
    staging = tmp_path / "s"
    (staging / "nms_connector").mkdir(parents=True)
    (staging / "nms_connector" / "__init__.py").write_text("x", encoding="utf-8")
    (staging / "strategicum-plugin.json").write_text(json.dumps({"id": "nomanssky", "version": "0.14.1"}),
                                                     encoding="utf-8")
    with pytest.raises(updater.UpdateError):
        updater.verify(staging, expected_version="0.15.0")


def test_a_download_missing_the_connector_is_refused(tmp_path):
    """A truncated or restructured archive must not replace a working install."""
    staging = tmp_path / "s"
    staging.mkdir()
    (staging / "strategicum-plugin.json").write_text(json.dumps({"id": "nomanssky", "version": "0.15.0"}),
                                                     encoding="utf-8")
    with pytest.raises(updater.UpdateError):
        updater.verify(staging, expected_version="0.15.0")


def test_a_download_of_another_plugin_is_refused(tmp_path):
    """The id is what says this is the same program; without the check a wrong URL could replace it."""
    staging = tmp_path / "s"
    (staging / "nms_connector").mkdir(parents=True)
    (staging / "nms_connector" / "__init__.py").write_text("x", encoding="utf-8")
    (staging / "strategicum-plugin.json").write_text(json.dumps({"id": "other", "version": "0.15.0"}),
                                                     encoding="utf-8")
    with pytest.raises(updater.UpdateError):
        updater.verify(staging, expected_version="0.15.0")


def test_a_downgrade_below_the_data_version_is_refused(tmp_path):
    """The data dir carries the highest `data_version` ever written. Going back to a version that cannot
    read it would read a newer format as junk, which the app calls danger."""
    stamp = {"data_version": 2}
    with pytest.raises(updater.UpdateError):
        updater.check_data_version(stamp, manifest={"data_version": 1}, confirmed=False)
    assert updater.check_data_version(stamp, manifest={"data_version": 1}, confirmed=True) is None


def test_an_equal_or_newer_data_version_needs_no_confirmation(tmp_path):
    """The ordinary case must not ask the user anything."""
    assert updater.check_data_version({"data_version": 1}, manifest={"data_version": 1},
                                      confirmed=False) is None
    assert updater.check_data_version({}, manifest={"data_version": 3}, confirmed=False) is None


def _install(tmp_path, marker="old"):
    install = tmp_path / "install"
    (install / "nms_connector").mkdir(parents=True)
    (install / "nms_connector" / f"marker-{marker}.py").write_text(marker, encoding="utf-8")
    (install / "strategicum-plugin.json").write_text("{}", encoding="utf-8")
    return install


def test_the_swap_keeps_the_previous_version_for_a_rollback(tmp_path):
    """An install that cannot start must be recoverable without the installer; the old code is kept, the
    way the app moves the old plugin to `.trash/`."""
    install = _install(tmp_path)
    staging = tmp_path / "staging"
    (staging / "nms_connector").mkdir(parents=True)
    (staging / "nms_connector" / "marker-new.py").write_text("new", encoding="utf-8")
    previous = updater.swap(install, staging, tmp_path / "backups")
    assert (install / "nms_connector" / "marker-new.py").exists()
    assert (previous / "nms_connector" / "marker-old.py").exists()


def test_the_swap_leaves_vendor_alone(tmp_path):
    """`vendor\\python` holds the running interpreter and the loaded numpy DLLs. Windows refuses to rename
    a directory with open handles, so an install-wide rename fails with WinError 32 - only the code
    folders are swapped, which is why the swap can run at all."""
    install = _install(tmp_path)
    (install / "vendor" / "python").mkdir(parents=True)
    (install / "vendor" / "python" / "python.exe").write_bytes(b"x")
    staging = tmp_path / "staging"
    (staging / "nms_connector").mkdir(parents=True)
    updater.swap(install, staging, tmp_path / "backups")
    assert (install / "vendor" / "python" / "python.exe").exists()


def test_the_swap_never_touches_the_data_dir(tmp_path):
    """The user's save-derived data, settings and Codex live outside the install folder; a swap that
    removed them would lose the planet history and every generated document."""
    install = _install(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    (data / "planet_history.json").write_text("{}", encoding="utf-8")
    staging = tmp_path / "staging"
    (staging / "nms_connector").mkdir(parents=True)
    updater.swap(install, staging, tmp_path / "backups")
    assert (data / "planet_history.json").exists()


def test_rollback_restores_the_previous_code(tmp_path):
    """The one guarantee that makes a self-update safe: if the new version does not start, the previous
    one comes back."""
    install = _install(tmp_path)
    staging = tmp_path / "staging"
    (staging / "nms_connector").mkdir(parents=True)
    (staging / "nms_connector" / "marker-new.py").write_text("new", encoding="utf-8")
    previous = updater.swap(install, staging, tmp_path / "backups")
    updater.rollback(install, previous)
    assert (install / "nms_connector" / "marker-old.py").exists()
    assert not (install / "nms_connector" / "marker-new.py").exists()


def test_the_apply_helper_waits_for_the_host_to_exit(monkeypatch):
    """The swap runs in a helper process after the host exits: a running host holds its own code folder
    (and on Windows its current directory), so it cannot replace it from inside. The helper must wait."""
    waited = []
    alive = [True, True, False]
    monkeypatch.setattr(updater, "_process_is_alive", lambda pid: alive.pop(0) if alive else False)
    monkeypatch.setattr(updater, "_sleep", lambda seconds: waited.append(seconds))
    updater.wait_for_exit(pid=1234, timeout_s=30)
    assert len(waited) == 2


def test_waiting_gives_up_after_the_timeout(monkeypatch):
    """A host that never exits must not leave the helper spinning for ever; the swap is then attempted
    anyway and fails loudly rather than silently doing nothing."""
    monkeypatch.setattr(updater, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(updater, "_sleep", lambda seconds: None)
    clock = iter([0.0, 10.0, 40.0])
    monkeypatch.setattr(updater, "_now", lambda: next(clock))
    updater.wait_for_exit(pid=1, timeout_s=30)      # returns instead of looping for ever


def test_the_pending_file_round_trips(tmp_path):
    """The host writes what the helper must do, and reads it back on the next start to decide whether the
    new version came up; a damaged file must read as "nothing pending"."""
    updater.write_pending(tmp_path, {"version": "0.15.0", "staging": "s", "pid": 7})
    assert updater.read_pending(tmp_path)["version"] == "0.15.0"
    (tmp_path / updater.PENDING_NAME).write_text("{broken", encoding="utf-8")
    assert updater.read_pending(tmp_path) == {}
    updater.clear_pending(tmp_path)
    assert updater.read_pending(tmp_path) == {}


def test_a_pending_update_whose_version_did_not_arrive_asks_for_a_rollback(tmp_path):
    """On the next start: the pending file names the version that was installed. If the manifest says
    something else, the new code did not come up and the previous tree must come back."""
    pending = {"version": "0.16.0", "previous": str(tmp_path / "prev")}
    assert updater.rollback_needed(pending, installed="0.15.0") is True
    assert updater.rollback_needed(pending, installed="0.16.0") is False
    assert updater.rollback_needed({"version": "0.16.0"}, installed="0.15.0") is False


def test_list_versions_reads_the_github_tags():
    """The real source of versions. A shape change must break a test, not the Updates page."""
    payload = json.dumps([{"name": "v0.15.0-beta.2"}, {"name": "v0.14.1"}]).encode("utf-8")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return payload

    assert updater.list_versions(opener=lambda req, timeout: FakeResponse()) == ["0.15.0-beta.2", "0.14.1"]


def test_a_failed_tag_listing_is_a_typed_error():
    """No network is normal; the page must show why instead of an empty list that looks like "no
    updates"."""
    def boom(request, timeout):
        raise OSError("no network")

    with pytest.raises(updater.UpdateError):
        updater.list_versions(opener=boom)


# --------------------------------------------------------------------------- the service and the routes


class FakeService:
    """The updates service as the routes see it."""

    def __init__(self):
        self.installed = []

    def versions(self):
        return {"installed": "0.15.0-beta.3", "channel": "pre-release",
                "versions": [{"version": "0.15.0-beta.4", "action": "update", "prerelease": True}]}

    def install_version(self, version, confirm_data=False):
        self.installed.append((version, confirm_data))
        return {"ok": True, "restart": True, "version": version, "message": "ready"}


def test_the_updates_route_lists_versions(tmp_path):
    """The page's Updates tab reads exactly this."""
    from standalone_fixtures import build_deps, call
    deps = build_deps(tmp_path, updater=FakeService())
    body = json.loads(call(deps, "GET", "/api/updates").body)
    assert body["versions"][0]["action"] == "update" and body["channel"] == "pre-release"


def test_the_install_route_refuses_a_junk_version(tmp_path):
    """The version becomes part of a URL and a tag name; it must look like a version before anything is
    downloaded."""
    from standalone_fixtures import build_deps, call
    service = FakeService()
    deps = build_deps(tmp_path, updater=service)
    assert call(deps, "POST", "/api/updates/install", {"version": "../../etc"}).status == 422
    assert call(deps, "POST", "/api/updates/install", {}).status == 422
    assert service.installed == []


def test_the_install_route_passes_the_data_confirmation(tmp_path):
    """A downgrade below the written data format needs the user's confirmation; the flag has to reach the
    service or the refusal can never be cleared."""
    from standalone_fixtures import build_deps, call
    service = FakeService()
    deps = build_deps(tmp_path, updater=service)
    body = json.loads(call(deps, "POST", "/api/updates/install",
                           {"version": "0.14.1", "confirm_data": True}).body)
    assert service.installed == [("0.14.1", True)] and body["restart"] is True


def test_the_routes_are_503_without_an_updater(tmp_path):
    """A copied install folder (no updater wired) must say so rather than fail obscurely."""
    from standalone_fixtures import build_deps, call
    deps = build_deps(tmp_path)
    assert call(deps, "GET", "/api/updates").status == 503
    assert call(deps, "POST", "/api/updates/install", {"version": "0.15.0"}).status == 503


def test_the_service_stages_a_version_and_writes_the_pending_file(tmp_path):
    """The host's half of an update: download, verify, write what the helper must do - and never swap
    anything itself."""
    from standalone.updates_service import UpdatesService
    install = tmp_path / "install"
    (install / "standalone").mkdir(parents=True)
    (install / "standalone" / "apply_update.py").write_text("x", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    launched = []
    from standalone.updates_service import UpdateSources
    sources = UpdateSources()
    sources.lister = lambda: ["0.15.0"]
    sources.downloader = lambda version: _tarball({
        "strategicum-plugin.json": json.dumps({"id": "nomanssky", "version": "0.15.0"}),
        "nms_connector/__init__.py": "x",
        "standalone/__main__.py": "x"})
    sources.launcher = lambda: launched.append(True)
    service = UpdatesService(install, data, "0.14.1", "pre-release", sources)
    result = service.install_version("0.15.0")
    pending = updater.read_pending(data)
    assert result["restart"] is True and launched == [True]
    assert pending["version"] == "0.15.0" and Path(pending["staging"]).is_dir()
    assert (install / "nms_connector").exists() is False      # nothing swapped in this process


def test_the_service_refuses_reinstalling_the_running_version(tmp_path):
    """There is nothing to do, and the restart dance would be confusing."""
    from standalone.updates_service import UpdatesService
    service = UpdatesService(tmp_path, tmp_path, "0.15.0", "pre-release")
    with pytest.raises(updater.UpdateError):
        service.install_version("0.15.0")


def test_the_service_rolls_back_when_the_new_version_did_not_come_up(tmp_path):
    """The guarantee that makes self-update safe. On the next start the pending file still names the
    version that was installed; if the manifest says otherwise, the previous code comes back."""
    from standalone.updates_service import UpdatesService
    install = _install(tmp_path, marker="old")
    previous = tmp_path / "backups" / "previous-1"
    (previous / "nms_connector").mkdir(parents=True)
    (previous / "nms_connector" / "marker-restored.py").write_text("back", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    updater.write_pending(data, {"version": "0.16.0", "previous": str(previous),
                                 "install": str(install)})
    service = UpdatesService(install, data, "0.15.0", "pre-release")
    message = service.finish_pending()
    assert "could not start" in message
    assert (install / "nms_connector" / "marker-restored.py").exists()
    assert updater.read_pending(data) == {}


def test_a_successful_start_clears_the_pending_file(tmp_path):
    """Otherwise the next start would roll a working version back."""
    from standalone.updates_service import UpdatesService
    data = tmp_path / "data"
    data.mkdir()
    updater.write_pending(data, {"version": "0.15.0", "previous": str(tmp_path / "p")})
    service = UpdatesService(tmp_path, data, "0.15.0", "pre-release")
    assert service.finish_pending() is None
    assert updater.read_pending(data) == {}


def test_versions_without_the_standalone_host_are_blocked_not_offered():
    """Found live on 2026-10-13: no published release contains `standalone/` at all. Installing one would
    replace the host with nothing - no page, no Updates tab, no way back - so such a version is listed
    with a reason instead of a button."""
    rows = updater.rows(["0.15.0-beta.3", "0.14.1"], installed="0.15.0-beta.3")
    assert rows[0]["action"] == "installed"
    assert rows[1]["action"] == "blocked" and "no standalone mode" in rows[1]["reason"]


def test_the_service_refuses_a_blocked_version_before_downloading(tmp_path):
    """No point fetching 0.3 MB to refuse it afterwards, and the user gets the real reason."""
    from standalone.updates_service import UpdatesService
    service = UpdatesService(tmp_path, tmp_path, "0.15.0-beta.3", "pre-release")
    with pytest.raises(updater.UpdateError, match="no standalone mode"):
        service.install_version("0.14.1")


def test_verify_is_the_backstop_for_a_download_without_the_host(tmp_path):
    """Even if a tag claims a high version, a tree without the host is refused before the swap."""
    staging = tmp_path / "s"
    (staging / "nms_connector").mkdir(parents=True)
    (staging / "nms_connector" / "__init__.py").write_text("x", encoding="utf-8")
    (staging / "strategicum-plugin.json").write_text(
        json.dumps({"id": "nomanssky", "version": "0.99.0"}), encoding="utf-8")
    with pytest.raises(updater.UpdateError, match="no standalone mode"):
        updater.verify(staging, expected_version="0.99.0")
