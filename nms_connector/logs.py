"""Logging for the modules that have no plugin context, and the helpers that keep failures visible but quiet.

``bind(ctx.logger)`` is called once by the connector, so every line of every module goes through the host's
``PluginLogger`` (category ``[No Man's Sky]``); before that (tests, scripts) it is the plain logger of the same name.

* ``warn_once`` - a failure that repeats every poll (a damaged file read every 5 s) is logged at once and again
  only after ``REPEAT_S`` seconds, so the log shows the problem without drowning in it.
* ``read_json`` - a JSON file that is *missing* is normal (nothing stored yet) and silent; one that exists but cannot
  be read is a warning that names the file and the reason, and the caller gets ``None``.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

REPEAT_S = 300.0


class _Sink:
    """The logger every module writes through: the plain logger until the connector binds the host's."""
    logger: logging.Logger | logging.LoggerAdapter = logging.getLogger("vox-core.plugin.nomanssky")


_seen: dict[str, float] = {}


def bind(logger) -> None:
    """Use the host's plugin logger from now on."""
    _Sink.logger = logger


def log() -> logging.Logger | logging.LoggerAdapter:
    return _Sink.logger


def warn_once(key: str, message: str, *args, now: float | None = None) -> bool:
    """Log a warning unless the same `key` was logged in the last REPEAT_S seconds; True when it was logged."""
    now = time.monotonic() if now is None else now
    last = _seen.get(key)
    if last is not None and now - last < REPEAT_S:
        return False
    _seen[key] = now
    _Sink.logger.warning("[NMS] " + message, *args)
    return True


def reset() -> None:
    """Forget what was logged (tests)."""
    _seen.clear()


def read_json(path: Path, what: str):
    """The parsed JSON of `path`, or None when the file is missing (silent) or unreadable (a warning naming `what`)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        warn_once(f"read:{path}", "%s %s is unreadable and is ignored: %s: %s", what, path, type(exc).__name__, exc)
        return None
