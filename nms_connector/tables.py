"""The game-file tables the connector needs besides the item database, loaded once per game build.

Each table has a module that knows its layout and a measured fallback for when the game's files cannot be read
(a game update that moved a field): timer durations (``timers``), frigate trait names (``frigates``), warp-range
bonuses (``ships``), settlement limits and perks (``settlements``) and every technology's stat modifiers
(``techstats``, from the same files as the warp-range bonuses, so those are derived from it instead of read twice).

Blocking (file reads); the connector calls ``load`` through ``ctx.run_blocking``.
"""

from __future__ import annotations

from . import frigates, game_terms, recipes, seasons, settlements, ships, store, techstats, timers, worlds


class GameTables:
    """The tables of one game build, each with its fallback; ``load`` again when the build changes."""

    def __init__(self, table_store: "store.TableStore | None" = None):
        self.store = table_store                    # gamedata/tables.json: what the persona needs without the game files
        self.stored_build: str | None = None        # set when the tables came from the store (build id of the game then)
        self.loaded = False
        self.build_id: str | None = None
        self.timers: dict | None = None             # durations of constructions and expeditions
        self.frigate_traits: dict | None = None     # {"traits": {...}} or {"error": ...}
        self.ships: dict | None = None              # warp-range bonuses (ships.tables_from)
        self.settlements: dict | None = None        # stat limits, judgement windows, perks
        self.tech = techstats.TechStats()           # what every technology does
        self.recipes = recipes.RecipeBook()         # refiner/cooking recipes and crafting requirements
        self.worlds = worlds.WorldBook()            # world types in the game's words (English + game language)
        self.terms = game_terms.GameTerms()         # the game's words for refiners, crafting, ... (both languages)
        self.seasons = seasons.SeasonBook()         # the expeditions (names, descriptions, reward names)

    def needs_load(self, install) -> bool:
        """True before the first load and after a game update (another build id)."""
        return not self.loaded or getattr(install, "build_id", None) != self.build_id

    def load(self, install) -> list[str]:
        """Read every table of this installation (None: not found - fallbacks only); returns one warning per
        table that fell back to built-in values."""
        self.build_id = getattr(install, "build_id", None)
        self.stored_build = None
        if install is None and self._load_stored():
            return [f"Game files not found: using the tables stored from game build {self.stored_build}"]
        self.timers = timers.load_tables(install)
        self.frigate_traits = frigates.load_traits(install)
        self.tech = techstats.load(install)
        self.ships = ships.load_tables(install, self.tech)
        self.settlements = settlements.load_tables(install)
        self.recipes = recipes.load(install)
        english, local, language, reason = self._read_texts(install)
        self._build_texts(english, local, language, reason)
        self._store(install, english, local, language)
        self.loaded = True
        warnings = []
        for label, table in (("Timer durations: built-in values", self.timers),
                             ("Frigate trait names unavailable", self.frigate_traits),
                             ("Warp range values: built-in", self.ships),
                             ("Settlement tables: built-in values", self.settlements),
                             ("Technology stats unavailable", self.tech),
                             ("Recipes unavailable", self.recipes),
                             ("World type names unavailable", self.worlds)):
            error = (table.error if isinstance(table, (techstats.TechStats, recipes.RecipeBook, worlds.WorldBook))
                     else table.get("error"))
            if error:
                warnings.append(f"{label} ({error})")
        return warnings

    @staticmethod
    def _wanted_text_key(key: str) -> bool:
        return worlds.wanted_key(key) or game_terms.term_keys_wanted(key) or seasons.wanted_key(key)

    @classmethod
    def _read_texts(cls, install):
        """(English texts, game-language texts, language, error) of the keys the books need: one pass over the
        language files (~1 s); the error names why they could not be read."""
        if install is None:
            return {}, None, None, "game installation not found"
        try:
            english, local, language = game_terms.read_language(install, cls._wanted_text_key)
            return english, local, language, None
        except (OSError, KeyError, ValueError, RuntimeError) as exc:
            return {}, None, None, f"{type(exc).__name__}: {exc}"

    def _build_texts(self, english, local, language, reason) -> None:
        """Worlds, terms and expeditions from the language texts (empty with the reason when there are none)."""
        if reason:
            self.worlds, self.terms = worlds.WorldBook(error=reason), game_terms.GameTerms(error=reason)
            self.seasons = seasons.SeasonBook(error=reason)
            return
        self.worlds = worlds.WorldBook.from_texts(english, local, language)
        self.terms = game_terms.GameTerms.from_texts(english, local, language)
        self.seasons = seasons.SeasonBook.from_texts(english, local, language)

    def _store(self, install, english, local, language) -> None:
        """Keep the recipes and texts of this build so the persona can answer without the game files."""
        if self.store is None or install is None or not self.recipes.recipes or not english:
            return
        plain = {"timers": self.timers, "frigate_traits": self.frigate_traits, "ships": self.ships,
                 "settlements": self.settlements}
        # Only tables that were really read: a fallback or an error is not worth keeping.
        plain = {k: v for k, v in plain.items() if isinstance(v, dict) and not v.get("error")
                 and v.get("source") == "game files"}
        self.store.save(self.build_id, language, self.recipes.to_json(),
                        {"english": english, "local": local, "language": language}, plain)

    def _load_stored(self) -> bool:
        """Adopt the stored tables (no installation): True when there were some. Timers, frigate traits, warp range,
        settlement limits and technology stats stay on their measured fallbacks."""
        data = self.store.load() if self.store is not None else None
        if not data:
            return False
        book = recipes.RecipeBook.from_json(data.get("recipes"))
        texts = data.get("texts") or {}
        if book.error or not texts.get("english"):
            return False
        self.recipes = book
        self._build_texts(texts["english"], texts.get("local"), texts.get("language"), None)
        stored = data.get("tables") or {}
        self.timers, self.frigate_traits = stored.get("timers"), stored.get("frigate_traits")
        self.ships, self.settlements = stored.get("ships"), stored.get("settlements")
        self.stored_build = data.get("build_id") or "unknown"
        self.loaded = True
        return True

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
