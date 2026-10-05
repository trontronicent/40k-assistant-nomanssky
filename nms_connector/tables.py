"""The game-file tables the connector needs besides the item database, loaded once per game build.

Each table has a module that knows its layout and a measured fallback for when the game's files cannot be read
(a game update that moved a field): timer durations (``timers``), frigate trait names (``frigates``), warp-range
bonuses (``ships``), settlement limits and perks (``settlements``) and every technology's stat modifiers
(``techstats``, from the same files as the warp-range bonuses, so those are derived from it instead of read twice).

Blocking (file reads); the connector calls ``load`` through ``ctx.run_blocking``.
"""

from __future__ import annotations

from . import frigates, settlements, ships, techstats, timers


class GameTables:
    """The tables of one game build, each with its fallback; ``load`` again when the build changes."""

    def __init__(self):
        self.loaded = False
        self.build_id: str | None = None
        self.timers: dict | None = None             # durations of constructions and expeditions
        self.frigate_traits: dict | None = None     # {"traits": {...}} or {"error": ...}
        self.ships: dict | None = None              # warp-range bonuses (ships.tables_from)
        self.settlements: dict | None = None        # stat limits, judgement windows, perks
        self.tech = techstats.TechStats()           # what every technology does

    def needs_load(self, install) -> bool:
        """True before the first load and after a game update (another build id)."""
        return not self.loaded or getattr(install, "build_id", None) != self.build_id

    def load(self, install) -> list[str]:
        """Read every table of this installation (None: not found - fallbacks only); returns one warning per
        table that fell back to built-in values."""
        self.build_id = getattr(install, "build_id", None)
        self.timers = timers.load_tables(install)
        self.frigate_traits = frigates.load_traits(install)
        self.tech = techstats.load(install)
        self.ships = ships.load_tables(install, self.tech)
        self.settlements = settlements.load_tables(install)
        self.loaded = True
        warnings = []
        for label, table in (("Timer durations: built-in values", self.timers),
                             ("Frigate trait names unavailable", self.frigate_traits),
                             ("Warp range values: built-in", self.ships),
                             ("Settlement tables: built-in values", self.settlements),
                             ("Technology stats unavailable", self.tech)):
            error = table.error if isinstance(table, techstats.TechStats) else table.get("error")
            if error:
                warnings.append(f"{label} ({error})")
        return warnings

    # The tables with their fallbacks: what the views use, loaded or not.

    @property
    def timer_durations(self) -> dict:
        return self.timers or timers.FALLBACK

    @property
    def ship_ranges(self) -> dict:
        return self.ships or ships.FALLBACK

    @property
    def settlement_rules(self) -> dict:
        return self.settlements or settlements.FALLBACK

    @property
    def trait_names(self) -> dict:
        return (self.frigate_traits or {}).get("traits") or {}
