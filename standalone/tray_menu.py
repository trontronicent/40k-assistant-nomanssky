"""The tray menu as a description: pure, so the decisions are testable without a tray.

Mirrors the app's `src/tray/menu_model.py` on purpose - what is shown, checked and which action a click
runs lives here, and `standalone/tray.py` only turns it into pystray items.
"""
from __future__ import annotations

import dataclasses

MAX_TEXT = 48          # Win32 menus do not wrap
MAX_TOOLTIP = 120      # Windows truncates a tray tooltip at 127 characters


@dataclasses.dataclass
class Entry:
    """One menu line. kind: action | check | separator | label."""

    kind: str
    text: str = ""
    local: str | None = None       # which tray action a click runs
    checked: bool = False
    enabled: bool = True
    default: bool = False


def cut(text: str, limit: int = MAX_TEXT) -> str:
    """Collapse whitespace and shorten; Win32 draws exactly what it is given."""
    collapsed = " ".join(str(text or "").split())
    return collapsed if len(collapsed) <= limit else collapsed[:limit - 1] + "…"


def tooltip(status: str, port: int) -> str:
    """What hovering the icon says: the state and where the page is."""
    return cut(f"No Man's Sky Companion - {status} (port {port})", MAX_TOOLTIP)


def build_menu(overlay_on: bool, ai_enabled: bool, update: str | None) -> list[Entry]:
    """The menu for the current state. The first entry is the default (a left click runs it)."""
    entries = [Entry("action", cut("Open No Man's Sky Companion"), local="open_page", default=True)]
    if ai_enabled:
        entries.append(Entry("action", cut("Ask the companion"), local="open_chat"))
    entries.append(Entry("separator"))
    entries.append(Entry("check", cut("Game overlay"), local="toggle_overlay", checked=bool(overlay_on)))
    entries.append(Entry("separator"))
    entries.append(Entry("action", cut("Read the save again"), local="rescan"))
    entries.append(Entry("action", cut(f"Version {update} is available") if update else "Check for updates…",
                         local="check_updates"))
    entries.append(Entry("separator"))
    entries.append(Entry("action", cut("Open the data folder"), local="open_data_folder"))
    entries.append(Entry("action", cut("Open the log"), local="open_log"))
    entries.append(Entry("separator"))
    entries.append(Entry("action", cut("Restart"), local="restart"))
    entries.append(Entry("action", cut("Quit"), local="quit"))
    return entries
