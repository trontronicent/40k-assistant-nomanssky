"""The Updates page's work: list the versions, and install one.

The host does the safe part (download, extract, verify, bound the data format), then hands the swap to
`apply_update.py` - see `updater` for why the swap cannot happen in this process.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from standalone import paths, updater

log = logging.getLogger("nms-standalone.updates")

STAGING_NAME = "staging"
BACKUPS_NAME = "backups"
DATA_STAMP = ".stc-data.json"      # the app writes this beside a plugin's data; we mirror it


@dataclasses.dataclass
class UpdateSources:
    """Where versions and code come from, and how the swap helper is started.

    A parameter object rather than three more constructor arguments (code-shape.md), and the seam the
    tests replace so they need no network.
    """

    lister = staticmethod(updater.list_versions)
    downloader = staticmethod(updater.download)
    launcher = None


class UpdatesService:
    """Everything the update routes call."""

    def __init__(self, install: Path, data_dir: Path, version: str, channel: str,
                 sources: UpdateSources | None = None):
        sources = sources or UpdateSources()
        self.install = Path(install)
        self.data_dir = Path(data_dir)
        self.version = version
        self.channel = channel
        self._list = sources.lister
        self._download = sources.downloader
        self._launch = sources.launcher or self._launch_helper

    # ---- listing ----------------------------------------------------------

    def versions(self) -> dict:
        """What the page shows: every offered version with its direction."""
        found = self._list()
        offered = updater.offered(found, self.channel, self.version)
        return {"installed": self.version, "channel": self.channel,
                "versions": updater.rows(offered, self.version)}

    # ---- installing -------------------------------------------------------

    def install_version(self, version: str, confirm_data: bool = False) -> dict:
        """Download, verify, then ask the helper to swap and restart. Returns what the page shows."""
        if version == self.version:
            raise updater.UpdateError("that version is already installed")
        if not updater.has_standalone(version):
            raise updater.UpdateError(
                f"v{version} has no standalone mode (it starts from "
                f"{updater.FIRST_STANDALONE_VERSION}); installing it would leave nothing to start")
        staging = self.data_dir / STAGING_NAME
        root = updater.extract(self._download(version), staging)
        manifest = updater.verify(root, version)
        updater.check_data_version(self._data_stamp(), manifest, confirm_data)
        pending = {
            "version": version,
            "install": str(self.install),
            "staging": str(root),
            "backups": str(self.data_dir / BACKUPS_NAME),
            "pid": _own_pid(),
            "python": sys.executable,
        }
        updater.write_pending(self.data_dir, pending)
        self._launch()
        log.info("v%s is staged; the helper will swap it in once this process exits", version)
        return {"ok": True, "restart": True, "version": version,
                "message": f"Version {version} is ready; the companion restarts now."}

    def _data_stamp(self) -> dict:
        """The highest data format the connector's data dir has seen, like the app's `.stc-data.json`."""
        try:
            return json.loads((paths.plugin_data_dir(self.data_dir) / DATA_STAMP)
                              .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _launch_helper(self) -> None:
        """Copy the helper out of the install tree and start it detached."""
        source = self.install / "standalone" / "apply_update.py"
        target = self.data_dir / "apply_update.py"
        shutil.copyfile(source, target)
        command = [_pythonw(), str(target), str(self.data_dir)]
        subprocess.Popen(command, cwd=str(self.data_dir))      # noqa: S603 - our own module
        log.info("the apply helper was started from %s", target)

    # ---- the start after a swap -------------------------------------------

    def finish_pending(self) -> str | None:
        """Called on every start. Returns a message when something had to be rolled back."""
        pending = updater.read_pending(self.data_dir)
        if not pending:
            return None
        if updater.rollback_needed(pending, self.version):
            log.error("v%s did not come up (this is v%s); rolling back",
                      pending.get("version"), self.version)
            updater.rollback(self.install, Path(pending["previous"]))
            updater.clear_pending(self.data_dir)
            return (f"Version {pending.get('version')} could not start, so the previous one was "
                    "restored. See apply_update.log.")
        updater.clear_pending(self.data_dir)
        return None


def _own_pid() -> int:
    import os
    return os.getpid()


def _pythonw() -> str:
    """The windowless interpreter beside the running one, so the helper opens no console."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return str(candidate) if candidate.is_file() else sys.executable
