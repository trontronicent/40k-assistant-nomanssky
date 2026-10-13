"""Swaps in a downloaded version after the host has exited, then starts it again.

This module is **copied out of the install folder** before it runs (into the data dir) and started as a
detached process, because it replaces the very folders the host runs from. On Windows a directory cannot
be renamed while a process holds a handle inside it or has it as its current directory.

It is started as a script, not imported:

    pythonw.exe <data>\\apply_update.py

Everything it needs is in `<data>/pending-update.json`, written by the host before it asked to be
restarted.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

LOG_NAME = "apply_update.log"
PENDING_NAME = "pending-update.json"

log = logging.getLogger("nms-standalone.apply")


def read_pending(data_dir: Path) -> dict:
    try:
        return json.loads((data_dir / PENDING_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_pending(data_dir: Path, pending: dict) -> None:
    tmp = data_dir / (PENDING_NAME + ".tmp")
    tmp.write_text(json.dumps(pending, indent=1), encoding="utf-8")
    tmp.replace(data_dir / PENDING_NAME)


def main() -> int:
    data_dir = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent)
    logging.basicConfig(filename=str(data_dir / LOG_NAME), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    pending = read_pending(data_dir)
    if not pending:
        log.error("there is nothing pending in %s", data_dir)
        return 1

    install = Path(pending["install"])
    sys.path.insert(0, str(install))               # the only import path: the install we are updating
    from standalone import updater                 # noqa: PLC0415 - must come after sys.path

    log.info("waiting for the host (pid %s) to exit", pending.get("pid"))
    updater.wait_for_exit(int(pending.get("pid") or 0))
    try:
        previous = updater.swap(install, Path(pending["staging"]), Path(pending["backups"]))
    except OSError as err:
        log.error("the swap failed, the install is untouched: %s", err)
        return 2
    pending["previous"] = str(previous)
    write_pending(data_dir, pending)
    log.info("swapped in v%s; the previous code is in %s", pending.get("version"), previous)

    command = [pending.get("python") or sys.executable, "-m", "standalone", "--no-browser"]
    try:
        subprocess.Popen(command, cwd=str(install))    # noqa: S603 - our own module
    except OSError as err:
        log.error("the host could not be started again: %s", err)
        return 3
    log.info("the host was started again")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
