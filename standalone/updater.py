"""Updates and downgrades the standalone install from the plugin's own GitHub tags.

No git and no third-party HTTP client: tags come from the GitHub API over `urllib`, the code from
`codeload.github.com/<owner>/<repo>/tar.gz/refs/tags/<tag>`. The install folder is per-user and
writable, so no elevation is involved.

**The swap does not run in the host.** On Windows a directory cannot be renamed while a process holds a
handle inside it or has it as its current directory, and `vendor\\python` holds the running interpreter
plus numpy's loaded `.pyd` files. So the host downloads and verifies, then `standalone/apply_update.py`
- copied out of the install tree - waits for it to exit, swaps only the code folders, and starts it
again. If the new code does not come up, the next start rolls back.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("nms-standalone.updater")

REPO = "trontronicent/40k-assistant-nomanssky"
TAGS_URL = f"https://api.github.com/repos/{REPO}/tags?per_page=100"
TARBALL_URL = f"https://codeload.github.com/{REPO}/tar.gz/refs/tags/"
USER_AGENT = "nms-companion-updater"
TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")
MAX_TARBALL_BYTES = 80 * 1024 * 1024
MAX_MEMBERS = 20000
TAGS_TIMEOUT_S = 30.0
DOWNLOAD_TIMEOUT_S = 180.0
PENDING_NAME = "pending-update.json"

# Standalone mode exists from this version on. Older tags are real plugin releases, but they contain no
# `standalone/` package at all: installing one would leave the program with no host to start - no page,
# no Updates tab, no way back. They are listed with a reason instead (the app marks a registry entry it
# cannot install the same way) and `verify` refuses them as the backstop.
FIRST_STANDALONE_VERSION = "0.15.0-beta.3"
EXIT_WAIT_S = 60.0

# Only these are replaced. `vendor/` holds the running interpreter and the loaded DLLs, which Windows
# will not let us rename, and the data dir is not in the install folder at all.
CODE_PARTS = ("nms_connector", "standalone", "codex", "strategicum-plugin.json", "HELP.md",
              "CHANGELOG.md", "README.md", "LICENSE", "THIRD-PARTY-NOTICES.md")

# Seams the tests replace (waiting for a process cannot be tested against the real clock).
_sleep = time.sleep
_now = time.time


class UpdateError(RuntimeError):
    """The update was refused or failed; the install is untouched (or rolled back)."""


# --------------------------------------------------------------------------- versions


def _pre_key(pre: str) -> tuple:
    """SemVer pre-release ordering: numeric parts compare as numbers (`beta.10` > `beta.2`)."""
    return tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in (pre or "").split("."))


def version_key(version: str) -> tuple:
    """Sort key: a release ranks above its own pre-releases, as SemVer orders them."""
    match = TAG_RE.match(version or "")
    if not match:
        return (0, 0, 0, 0, ())
    major, minor, patch, pre = match.groups()
    return (int(major), int(minor), int(patch), 0 if pre else 1, _pre_key(pre or ""))


def parse_tags(tags: list[str]) -> list[str]:
    """Version strings of the tags that are versions, newest first."""
    versions = {match.group(0).lstrip("v") for match in (TAG_RE.match(tag or "") for tag in tags) if match}
    return sorted(versions, key=version_key, reverse=True)


def is_prerelease(version: str) -> bool:
    match = TAG_RE.match(version or "")
    return bool(match and match.group(4))


def offered(versions: list[str], channel: str, installed: str) -> list[str]:
    """What the page lists. On stable, pre-releases are dropped - except the installed one, which must
    stay visible so the user can see what they are running."""
    if channel == "pre-release":
        return list(versions)
    return [v for v in versions if not is_prerelease(v) or v == installed]


def has_standalone(version: str) -> bool:
    """Whether that release carries the standalone host at all."""
    return version_key(version) >= version_key(FIRST_STANDALONE_VERSION)


def rows(versions: list[str], installed: str) -> list[dict]:
    """Each offered version with its direction, so the page can label the button. A version without the
    standalone host is `blocked` and says why - it would leave nothing to start."""
    out = []
    for version in versions:
        row = {"version": version, "prerelease": is_prerelease(version)}
        if version == installed:
            row["action"] = "installed"
        elif not has_standalone(version):
            row["action"] = "blocked"
            row["reason"] = f"no standalone mode before {FIRST_STANDALONE_VERSION}"
        elif version_key(version) > version_key(installed):
            row["action"] = "update"
        else:
            row["action"] = "downgrade"
        out.append(row)
    return out


def list_versions(opener=urllib.request.urlopen) -> list[str]:
    """The repository's tags, newest first. Raises `UpdateError` rather than showing an empty list, which
    the user would read as "no updates"."""
    request = urllib.request.Request(TAGS_URL, headers={"Accept": "application/vnd.github+json",
                                                        "User-Agent": USER_AGENT})
    try:
        with opener(request, timeout=TAGS_TIMEOUT_S) as response:
            data = json.loads(response.read())
    except (OSError, urllib.error.URLError, ValueError) as err:
        raise UpdateError(f"could not read the versions: {err}") from err
    if not isinstance(data, list):
        raise UpdateError("the tag listing had an unexpected shape")
    return parse_tags([entry.get("name", "") for entry in data if isinstance(entry, dict)])


# --------------------------------------------------------------------------- download


def download(version: str, opener=urllib.request.urlopen) -> bytes:
    request = urllib.request.Request(TARBALL_URL + f"v{version}", headers={"User-Agent": USER_AGENT})
    try:
        with opener(request, timeout=DOWNLOAD_TIMEOUT_S) as response:
            data = response.read(MAX_TARBALL_BYTES + 1)
    except (OSError, urllib.error.URLError) as err:
        raise UpdateError(f"could not download v{version}: {err}") from err
    if len(data) > MAX_TARBALL_BYTES:
        raise UpdateError("the download is larger than expected")
    return data


def extract(data: bytes, staging: Path) -> Path:
    """Unpack into a staging folder, refusing any member that would escape it. GitHub wraps everything
    in one top-level folder, which is stripped."""
    staging = Path(staging)
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = tar.getmembers()
        _check_members(members, staging)
        tar.extractall(staging)                      # noqa: S202 - every member checked above
    tops = [path for path in staging.iterdir() if path.is_dir()]
    if len(tops) != 1:
        raise UpdateError("the archive does not have exactly one top-level folder")
    return tops[0]


def _check_members(members: list, staging: Path) -> None:
    if len(members) > MAX_MEMBERS:
        raise UpdateError("the archive has too many entries")
    root = str(staging.resolve())
    for member in members:
        if member.issym() or member.islnk():
            raise UpdateError(f"the archive contains a link: {member.name}")
        if not (member.isfile() or member.isdir()):
            raise UpdateError(f"the archive contains a special file: {member.name}")
        target = str((staging / member.name).resolve())
        if not (target == root or target.startswith(root + os.sep)):
            raise UpdateError(f"the archive would write outside the staging folder: {member.name}")


def verify(root: Path, expected_version: str) -> dict:
    """The manifest must be there, say this id and this version, and the entry module must exist - the
    checks the app's `_deploy` makes before it swaps anything in."""
    try:
        manifest = json.loads((Path(root) / "strategicum-plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise UpdateError(f"the download has no readable manifest: {err}") from err
    if manifest.get("id") != "nomanssky":
        raise UpdateError("the download is a different plugin")
    if manifest.get("version") != expected_version:
        raise UpdateError(f"the tag says {expected_version}, the manifest {manifest.get('version')}")
    if not (Path(root) / "nms_connector" / "__init__.py").is_file():
        raise UpdateError("the download has no nms_connector package")
    if not (Path(root) / "standalone" / "__main__.py").is_file():
        raise UpdateError(f"v{expected_version} has no standalone mode (it starts from "
                          f"{FIRST_STANDALONE_VERSION}); installing it would leave nothing to start")
    return manifest


def check_data_version(stamp: dict, manifest: dict, confirmed: bool) -> None:
    """Refuse a downgrade below the data format already written, unless the user confirmed it - the app's
    `data_compatibility` danger level, which standalone has no dialog for otherwise."""
    written = int((stamp or {}).get("data_version") or 0)
    wanted = int((manifest or {}).get("data_version") or 0)
    if wanted and written > wanted and not confirmed:
        raise UpdateError(f"this version reads data format {wanted}, your data is {written}; "
                          "confirm to continue")


# --------------------------------------------------------------------------- the swap


def swap(install: Path, new_root: Path, backups: Path) -> Path:
    """Move this version's **code** aside (kept for a rollback) and the new code into place, part by
    part. Never `vendor/`, never the data dir. Runs in the apply helper, not in the host."""
    install, new_root, backups = Path(install), Path(new_root), Path(backups)
    backups.mkdir(parents=True, exist_ok=True)
    previous = backups / f"previous-{int(_now())}"
    previous.mkdir()
    moved: list[tuple[Path, Path]] = []
    try:
        for part in CODE_PARTS:
            _swap_part(install, new_root, previous, part, moved)
    except OSError:
        for target, source in moved:                 # put back what was already moved
            if not source.exists():
                target.rename(source)
        raise
    return previous


def _swap_part(install: Path, new_root: Path, previous: Path, part: str,
               moved: list[tuple[Path, Path]]) -> None:
    source = install / part
    if source.exists():
        target = previous / part
        source.rename(target)
        moved.append((target, source))
    incoming = new_root / part
    if incoming.exists():
        incoming.rename(install / part)


def rollback(install: Path, previous: Path) -> None:
    """Bring the previous code back after a failed start."""
    install, previous = Path(install), Path(previous)
    for part in CODE_PARTS:
        kept = previous / part
        if not kept.exists():
            continue
        live = install / part
        if live.is_dir():
            shutil.rmtree(live, ignore_errors=True)
        elif live.exists():
            live.unlink()
        kept.rename(live)


def _process_is_alive(pid: int) -> bool:
    """True while that process still exists (`os.kill(pid, 0)` works on Windows Python too)."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def wait_for_exit(pid: int, timeout_s: float = EXIT_WAIT_S) -> None:
    """Wait until the host process is gone, so its files are free."""
    deadline = _now() + timeout_s
    while _now() < deadline and _process_is_alive(pid):
        _sleep(0.25)


# --------------------------------------------------------------------------- the pending file


def write_pending(data_dir: Path, pending: dict) -> None:
    path = Path(data_dir) / PENDING_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(pending, indent=1), encoding="utf-8")
    tmp.replace(path)


def read_pending(data_dir: Path) -> dict:
    try:
        raw = json.loads((Path(data_dir) / PENDING_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def clear_pending(data_dir: Path) -> None:
    (Path(data_dir) / PENDING_NAME).unlink(missing_ok=True)


def rollback_needed(pending: dict, installed: str) -> bool:
    """True when a swap happened but the version now installed is not the one that was asked for: the new
    code did not come up, so the previous tree must come back."""
    if not pending or not pending.get("previous"):
        return False
    return bool(pending.get("version")) and pending["version"] != installed
