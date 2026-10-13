"""The standalone host's settings file (`<data>/standalone.json`). The installer writes it once; the host
reads it on every start and the settings page updates single keys."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

DEFAULT_PORT = 8787
DEFAULT_CHAT_MODEL = ""
DEFAULT_EMBED_MODEL = "nomic-embed-text"
DEFAULT_VOICE = "en_GB-cori-high"
CHANNELS = ("stable", "pre-release")


@dataclasses.dataclass(frozen=True)
class Settings:
    """Everything the user can turn on or off. Defaults = a working install with nothing optional."""

    port: int = DEFAULT_PORT
    ai_enabled: bool = False
    chat_model: str = DEFAULT_CHAT_MODEL
    embed_model: str = DEFAULT_EMBED_MODEL
    ollama_url: str = "http://127.0.0.1:11434"
    tts_enabled: bool = False
    voice: str = DEFAULT_VOICE
    overlay_enabled: bool = True
    tray_enabled: bool = True
    codex_enabled: bool = True
    update_channel: str = "pre-release"


FIELD_TYPES = {f.name: f.type for f in dataclasses.fields(Settings)}


def load(path: Path) -> Settings:
    """Read the settings; a missing or damaged file reads as the defaults (the caller logs it)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()
    kwargs = {k: v for k, v in raw.items() if k in FIELD_TYPES}
    try:
        return Settings(**kwargs)
    except TypeError:
        return Settings()


def save(path: Path, settings: Settings) -> None:
    """Write the settings atomically (a half-written file would read as defaults on the next start)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dataclasses.asdict(settings), indent=2), encoding="utf-8")
    tmp.replace(path)


def replace(settings: Settings, changes: dict) -> Settings:
    """A copy with `changes` applied; unknown keys are the caller's problem to refuse, not ours."""
    return dataclasses.replace(settings, **changes)


def as_dict(settings: Settings) -> dict:
    return dataclasses.asdict(settings)
