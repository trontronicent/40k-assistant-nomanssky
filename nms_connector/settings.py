"""The plugin's own settings (the page's *Settings* tab), kept in ``settings.json`` in its data folder.

* ``single_context`` - **Single Context Per Question**: the plugin persona answers each question without the
  earlier turns of the conversation. The game data is fresh with every question anyway, so little is lost, and the
  model's context (its KV cache in VRAM) stays small - useful while the game itself needs the graphics card. The
  app applies it (app 3.11.0: ``chat_context`` returns ``single_context``; prompt_builder keeps only the current
  question for this plugin's own persona). Off by default.
* ``codeword`` - the word that addresses the plugin persona in Live Comms' Codeword mode ("Atlas, how much copper do
  I have?"). The desktop overlay, switched to this plugin, sends it to the app when you press *Codeword*.

Form values are untrusted: ``update`` checks them and answers what was wrong; a damaged file gives the defaults.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_CODEWORD = "Atlas"
CODEWORD_RE = re.compile(r"^[\w' -]{1,40}$", re.UNICODE)    # the app's overlay accepts the same


@dataclass
class PluginSettings:
    """The settings and where they are stored."""
    single_context: bool = False
    codeword: str = DEFAULT_CODEWORD

    @classmethod
    def load(cls, path: Path) -> PluginSettings:
        """The stored settings; defaults for a missing or damaged file (and for a stored value that is invalid)."""
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        out = cls()
        if isinstance(raw.get("single_context"), bool):
            out.single_context = raw["single_context"]
        if isinstance(raw.get("codeword"), str) and CODEWORD_RE.match(raw["codeword"].strip()):
            out.codeword = raw["codeword"].strip()
        return out

    def save(self, path: Path) -> None:
        """Write atomically (temp file + replace)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(path)

    SWITCHES = {"single_context": ("Single context per question", "Helps saving VRAM")}

    def set_switch(self, params: dict) -> str | None:
        """One on/off setting from the app's overlay (``{id, value}``, untrusted); returns why it was refused."""
        if not isinstance(params.get("id"), str) or params["id"] not in self.SWITCHES:
            return "Unknown setting."
        if not isinstance(params.get("value"), bool):
            return "The value must be on or off."
        setattr(self, params["id"], params["value"])
        return None

    def toggles(self, action: str) -> list[dict]:
        """The on/off settings for the app's overlay (app 3.11.0 ``toggles``): clicking runs ``action``."""
        return [{"id": key, "label": label, "hint": hint, "value": bool(getattr(self, key)), "action": action}
                for key, (label, hint) in self.SWITCHES.items()]

    def update(self, params: dict) -> str | None:
        """Apply the settings form's values (untrusted); returns why they were refused, or None when applied."""
        codeword = " ".join(str(params.get("codeword") or "").split())
        if not CODEWORD_RE.match(codeword):
            return "The codeword needs 1-40 letters, digits, spaces, hyphens or apostrophes."
        single = params.get("single_context")
        if not isinstance(single, bool):
            return "Single Context Per Question must be on or off."
        self.codeword, self.single_context = codeword, single
        return None
