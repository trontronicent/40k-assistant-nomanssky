"""Search the recorded planets by what they are like: "sengend heiß", "toxic rain", "Kupfer", "no sentinels" (pure).

Every recorded planet is indexed by the texts the Planets table shows - name and system, type (the game's
description, e.g. "Sengend heißer Planet" / "Scorched Planet"), weather, the three resources, plants, harvester gas,
flora, fauna and sentinels - in English and the game's language (planets_view.Texts gives both). Words are
compared case-insensitively with ß = ss and ä/ö/ü = ae/oe/ue, and a search word matches every word that starts
with it ("heiss" finds "heißer", "sengend" finds "Sengender"), so the player can type as the game writes it or
loosely.

German adjectives are inflected ("stickige Welt", "giftigen Planeten"), so a search word also matches through its
stem (``stem``: -e/-er/-en/-es/-em dropped, >= 3 letters left - "stickige" finds the weather "Stickig").
Every planet is also indexed with the words of its world type's names in both languages (``Context.world_words``
from worlds.WorldBook.biome_words): "stickige" finds every airless planet, also one the game calls "Leerer Planet".

* ``PlanetIndex.search(query)`` - every word of the query must match (the page's search field);
* ``PlanetIndex.best(question)`` - for a chat question: the words that are not question words ("wo", "gibt",
  "planet", "where" ...), planets ranked by how many of them match, then by distance (the persona).
"""

from __future__ import annotations

import re
import unicodedata

from . import galaxy

MIN_TERM = 3
MAX_QUERY_CHARS = 80
# Words of a question that say "planet" or ask, not what the planet is like (English and German).
QUESTION_WORDS = {
    "planet", "planets", "planeten", "welt", "welten", "world", "worlds", "mond", "monde", "moon", "moons",
    "where", "which", "what", "find", "search", "show", "list", "there", "with", "have", "know", "known", "nearest",
    "closest", "near", "best", "good", "any", "some", "the", "and", "for", "are", "can", "does",
    "wo", "gibt", "welche", "welcher", "welches", "finde", "such", "suche", "zeig", "zeige", "liste", "mit", "habe",
    "kenne", "bekannt", "bekannte", "naechste", "naechsten", "nahe", "beste", "gute", "einen", "eine", "einem",
    "einer", "der", "die", "das", "den", "dem", "und", "fuer", "sind", "ist", "kann", "ich", "mir", "mich", "meine",
    "mein", "you", "your", "there", "ein", "auf", "von", "bei", "nach", "how", "wie", "viele", "many", "all", "alle",
    # "Habe ich bereits eine stickige Welt entdeckt?" - asking whether, not what the planet is like (2026-10-06)
    "bereits", "schon", "entdeckt", "entdecken", "besucht", "gefunden", "jemals", "irgendeine", "irgendwo", "hab",
    "discovered", "visited", "already", "ever", "found", "been", "seen", "gesehen", "kennst", "hast",
}
GERMAN_ENDINGS = ("en", "er", "es", "em", "e")


def stem(word: str) -> str:
    """A folded word without a German adjective ending: 'stickige' -> 'stickig', 'giftigen' -> 'giftig',
    'toten' -> 'tot'; at least 3 letters stay, and the stem is only ever matched against word starts."""
    for end in GERMAN_ENDINGS:
        if word.endswith(end) and len(word) - len(end) >= 3 and len(word) >= 5:
            return word[:-len(end)]
    return word


def fold(text: str | None) -> str:
    """Lower case, ß -> ss, ä/ö/ü -> ae/oe/ue, other accents dropped: 'Sengend heißer' -> 'sengend heisser'."""
    text = (text or "").casefold().replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def words(text: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(text))


def terms(query: str, drop_question_words: bool = False) -> list[str]:
    """The search words of a query (>= MIN_TERM letters; without question words for a chat question)."""
    out = [w for w in words((query or "")[:MAX_QUERY_CHARS * 4]) if len(w) >= MIN_TERM]
    if drop_question_words:
        out = [w for w in out if w not in QUESTION_WORDS]
    return list(dict.fromkeys(out))


def _cell_text(cell) -> str:
    if isinstance(cell, dict):
        return str(cell.get("text") or "")
    return "" if cell is None else str(cell)


class PlanetIndex:
    """The recorded planets with their searchable words (built per view or question from a planets_view.Context)."""

    def __init__(self, ctx, planet_row, system_label):
        """`planet_row(texts, planet, visit, sentinel_index)` and `system_label(key, visit)` come from planets_view
        (passed in to keep this module free of a circular import)."""
        self.ctx = ctx
        self.entries = []
        for key, planets in ctx.recorded.items():
            visit = ctx.visit(key)
            label = system_label(key, visit)
            for planet in planets:
                row = planet_row(ctx.texts, planet, visit, ctx.sentinel_index)
                text = " ".join([label, planet.get("biome") or "", planet.get("size") or ""]
                                + [_cell_text(c) for c in row])
                world = set((getattr(ctx, "world_words", None) or {}).get(planet.get("biome") or "", ()))
                self.entries.append({"planet": planet, "system": key, "system_label": label, "row": row,
                                     "words": set(words(text)) | world})

    @staticmethod
    def _matches(term: str, planet_words: set[str]) -> bool:
        base = stem(term)
        return any(w.startswith(term) or w.startswith(base) for w in planet_words)

    def _distance(self, key):
        return galaxy.distance_ly(self.ctx.origin, key) if self.ctx.origin is not None else None

    def _ranked(self, found):
        def rank(item):
            entry, matched = item
            dist = self._distance(entry["system"])
            return (-len(matched), dist is None, dist or 0.0, entry["system_label"], entry["planet"].get("name") or "")
        return sorted(found, key=rank)

    def search(self, query: str) -> list[tuple[dict, list[str]]]:
        """Planets matching every word of the query (the page's search field), nearest first."""
        wanted = terms(query)
        if not wanted:
            return []
        found = [(e, wanted) for e in self.entries if all(self._matches(t, e["words"]) for t in wanted)]
        return self._ranked(found)

    def best(self, question: str, limit: int | None = 8) -> tuple[list[str], list[tuple[dict, list[str]]]]:
        """(search words, planets matching most of them, nearest first; all of them with limit None) for a chat
        question; ([], []) when the question names nothing a planet could be searched by."""
        wanted = terms(question, drop_question_words=True)
        if not wanted:
            return [], []
        found = []
        for entry in self.entries:
            matched = [t for t in wanted if self._matches(t, entry["words"])]
            if matched:
                found.append((entry, matched))
        if not found:
            return wanted, []
        top = max(len(m) for _, m in found)
        ranked = self._ranked([f for f in found if len(f[1]) == top])
        return wanted, ranked if limit is None else ranked[:limit]

    def distance_text(self, key) -> str:
        if self.ctx.origin is None:
            return "distance unknown"
        return galaxy.distance_text(self._distance(key), key == self.ctx.origin)
