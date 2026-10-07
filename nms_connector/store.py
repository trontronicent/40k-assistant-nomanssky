"""The game-file tables kept in the plugin's data folder, so the persona works without the game files.

The item database already has its own cache (``gamedata/items.json``). The other tables the persona needs - the recipe
book (refiner and cooking recipes, crafting requirements), the language texts of the world types, game terms and
expeditions, and the timer, frigate-trait, warp-range and settlement tables (JSON: tuples come back as lists, which
nothing here tells apart) - are written to ``gamedata/tables.json`` after every successful read of the game files, per game build.
When the installation cannot be found (another drive, an uninstalled game, a library that is offline) the connector
loads them from there and says so; the save files and the live-memory history (``planet_history.json``,
``settlement_screen.json``) are in the data folder or the save folder anyway. A game that is merely *not running*
changes nothing: everything the plugin reads from the game's files, and from the save, is on disk.

Never raises: an unreadable store is "nothing stored".
"""

from __future__ import annotations

import json
import time
from pathlib import Path

STORE_FORMAT = 1


class TableStore:
    """``gamedata/tables.json`` of one data folder."""

    def __init__(self, data_dir: Path):
        self.file = Path(data_dir) / "gamedata" / "tables.json"

    def save(self, build_id: str | None, language: str | None, recipes: dict, texts: dict,
             tables: dict | None = None) -> bool:
        """Write the tables (atomically); False when they could not be written."""
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"format": STORE_FORMAT, "build_id": build_id, "language": language,
                                       "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "recipes": recipes,
                                       "texts": texts, "tables": tables or {}}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.file)
            return True
        except (OSError, TypeError, ValueError):
            return False

    def load(self) -> dict | None:
        """The stored tables, or None when there are none (or they are from another store format)."""
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("format") != STORE_FORMAT:
            return None
        return data
