"""Where the standalone host keeps things. Pure functions over an environment mapping, so tests can pass
a fake one instead of touching the real machine."""
from __future__ import annotations

import os
from pathlib import Path

APP_FOLDER = "NMS Companion"


def install_root() -> Path:
    """The folder the program was installed into (the parent of the `standalone` package)."""
    return Path(__file__).resolve().parent.parent


def data_dir(env: dict[str, str] | None = None) -> Path:
    """User data: settings, the connector's data dir, the Codex, logs. Deliberately outside the install
    folder, which an update replaces wholesale."""
    env = os.environ if env is None else env
    local = env.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_FOLDER
    home = env.get("USERPROFILE") or env.get("HOME") or "."
    return Path(home) / ".nms-companion"


def plugin_data_dir(data: Path) -> Path:
    """The connector's own data dir. Never the app's `plugins/.data/nomanssky`: two hosts writing one
    data dir would fight over `planet_history.json`."""
    return data / "plugin"


def log_file(data: Path) -> Path:
    return data / "standalone.log"


def vendor_dir() -> Path:
    """Python runtime and wheels the installer placed beside the code."""
    return install_root() / "vendor"


def piper_dir(data: Path) -> Path:
    """Where the installer puts piper.exe and its voice files."""
    return data / "piper"


def codex_dir(data: Path) -> Path:
    """The standalone Codex library (one folder of Markdown documents)."""
    return data / "codex"


def settings_file(data: Path) -> Path:
    return data / "standalone.json"
