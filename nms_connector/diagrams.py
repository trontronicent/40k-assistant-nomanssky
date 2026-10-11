"""Recipes as structured data for the app's chat diagrams (app 3.17.0: ``chat_context`` -> ``recipes``).

Chat tests 2026-10-10/11: asking the model to copy the "A + B -> C" lines verbatim did not hold - it wrote
"1 Kuchenteig + 1 Anormale Marmelade + 1 Sahne [K2]" (no arrow, no result) or only "created ... from a base of
Wailing Batter". So the plugin hands the app the recipes it found for the question as data, and the app draws them
under the reply whatever the model writes. One entry per recipe: ingredients and result with amount, name in the
question's language and icon (the converted PNG, when there is one), and the station.
"""

from __future__ import annotations

import re

from . import recipes

MAX_DIAGRAMS = 12           # the app keeps at most 12 (plugins/diagrams.py)
MAX_PER_KIND = 6            # refiner / Nutrient Processor recipes per item, best first (as in the persona's lines)
# Words that only a German question has: with no item name to tell, they decide that the names are German.
GERMAN_HINTS = {"wie", "ich", "der", "die", "das", "den", "dem", "und", "mache", "machen", "herstellen", "stelle",
                "bekomme", "bekommen", "kann", "brauche", "rezept", "rezepte", "ein", "eine", "einen", "was", "wo",
                "mit", "koche", "kochen"}


def answer_language(question: str, items: list[str], lookup, game_language: str) -> str:
    """The language of the names: the game's own language when the question names an item that way (or, for
    German, reads as German), else English - the persona answers in the player's language."""
    if not game_language or game_language in (recipes.ENGLISH, "usenglish"):
        return recipes.ENGLISH
    text = (question or "").casefold()
    for item in items:
        entry = lookup(item) or {}
        local, en = entry.get("local"), entry.get("en")
        if local and local != en and local.casefold() in text:
            return game_language
        if en and en.casefold() in text:
            return recipes.ENGLISH
    if game_language == "german" and set(re.findall(r"[\w'-]+", text)) & GERMAN_HINTS:
        return game_language
    return recipes.ENGLISH


def _item(lookup, icon_name, item: str, amount: int, language: str) -> dict:
    out = {"amount": amount, "name": recipes.name_in(lookup, item, language)}
    icon = icon_name(item)
    if icon:
        out["icon"] = icon
    return out


def recipe_diagram(lookup, icon_name, r: recipes.Recipe, language: str, terms) -> dict:
    """One refiner or Nutrient Processor recipe."""
    return {"ingredients": [_item(lookup, icon_name, i, a, language) for i, a in r.ingredients],
            "result": _item(lookup, icon_name, r.result, r.amount, language),
            "station": recipes.station_name(r, language, terms)}


def item_diagrams(book, lookup, icon_name, items: list[str], language: str, terms) -> list[dict]:
    """Every recipe that makes these items: refiner, Nutrient Processor, crafting - at most MAX_DIAGRAMS."""
    out: list[dict] = []
    for item in items:
        made = book.made_by(item)[:MAX_PER_KIND] + book.made_by(item, cooking=True)[:MAX_PER_KIND]
        out += [recipe_diagram(lookup, icon_name, r, language, terms) for r in made]
        crafted = book.crafting.get(item)
        if crafted:
            out.append({"ingredients": [_item(lookup, icon_name, i, a, language) for i, a in crafted],
                        "result": _item(lookup, icon_name, item, 1, language)})
    return out[:MAX_DIAGRAMS]
