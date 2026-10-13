"""One host per data dir.

Two hosts over one data dir would both write the connector's `planet_history.json`, `items.json` and
Codex state, which is how that file gets corrupted. So a start records a lock naming its port, and a
second start opens the page that is already serving instead of becoming a rival.

A stale lock (after a crash) is ignored: the port is probed, and only an answering host counts.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
from pathlib import Path

log = logging.getLogger("nms-standalone.instance")

LOCK_NAME = "host.lock"
PROBE_TIMEOUT_S = 0.3        # a closed localhost port costs ~2 s on Windows without this


def responds(port: int) -> bool:
    """Whether something is listening on that port of this machine."""
    with socket.socket() as probe:
        probe.settimeout(PROBE_TIMEOUT_S)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def running_port(data_dir: Path) -> int | None:
    """The port of a host already serving this data dir, or None."""
    try:
        raw = json.loads((Path(data_dir) / LOCK_NAME).read_text(encoding="utf-8"))
        port = int(raw["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if responds(port):
        return port
    log.info("a stale lock named port %s; nothing is serving there", port)
    return None


@contextlib.contextmanager
def hold(data_dir: Path, port: int):
    """Record this host's lock for as long as it serves; removed in `finally`, failure path included."""
    path = Path(data_dir) / LOCK_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": os.getpid(), "port": port}), encoding="utf-8")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
