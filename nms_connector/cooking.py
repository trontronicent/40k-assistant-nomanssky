"""Cooking for the persona: what a dish needs, what you can cook right now, which dishes are worth most.

The Nutrient Processor's recipes come from the game's recipe table (``recipes.RecipeBook``: 1,323 recipes, 333 dishes
on build 25732212; every ingredient and result amount is 1). Raw, they are unreadable for a persona: the "Fibrous Stew"
alone has 33 ingredient pairs. ``pools`` folds them into "any of A, B + any of C, D" (ingredients with the same set
of partners form one pool, so the fold is exact), ``cookable`` matches the recipes against the player's holdings
and ranks the dishes by base value, and ``cooking_lines`` assembles the block for one question.

Researched (2026-10-07, see ``research/cooking.json``): the Nutrient Processor stands in a base, on the freighter
and in the Space Anomaly; edible products give temporary buffs; they can be sold to visiting pilots and Galactic
Trade Terminals; Iteration Cronus in the Anomaly rates dishes and pays 0-130 Nanites.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import logs

RESEARCH_FILE = Path(__file__).resolve().parent.parent / "research" / "cooking.json"
DISH_CATEGORIES = {"Edible Product", "Compressed Nutrients"}       # the game's category of a cooked dish
COOKING_WORDS = {"cook", "cooks", "cooking", "cooked", "kochen", "koche", "kochst", "kocht", "gekocht", "kochrezept",
                 "kochrezepte", "nutrient", "processor", "nährstoffprozessor", "naehrstoffprozessor", "dish", "dishes",
                 "meal", "meals", "gericht", "gerichte", "food", "essen", "stew", "eintopf", "cake", "kuchen",
                 "edible", "edibles", "cronus", "bake", "baking", "backen"}
HOW_WORDS = {"how", "make", "makes", "recipe", "recipes", "need", "needs", "ingredients", "ingredient", "get", "wie",
             "rezept", "rezepte", "brauche", "braucht", "benötige", "zutaten", "zutat", "herstellen", "machen",
             "bekomme", "what", "was", "with"}
LOW_WORDS = {"cheapest", "cheap", "least", "lowest", "worst", "billigste", "billigsten", "günstigste", "günstigsten",
             "niedrigste", "niedrigsten", "wertloseste"}
GOOD_WORDS = {"best", "most", "valuable", "profit", "profitable", "worth", "beste", "besten", "wertvollste",
              "wertvollsten", "meisten", "lohnt", "lohnend", "teuerste", "teuersten", "highest", "höchste", "höchsten"}
NOW_WORDS = {"right", "now", "currently", "have", "has", "own", "inventory", "materials", "ingredients", "can", "could",
             "kann", "könnte", "habe", "hab", "jetzt", "gerade", "aktuell", "besitze", "zutaten", "vorrat"}
MAX_POOL_LINES = 6              # ingredient lines per dish before "... and N more"
MAX_DISHES = 6                  # dishes shown for a "what can I cook / best dish" question
MAX_NAMED = 3                   # dishes or ingredients a question may name
MAX_POOL_NAMES = 8              # ingredient names listed per pool before "... (N more)"


def load_research(path: Path | None = None) -> dict:
    """The researched cooking facts ({} when the file is missing)."""
    data = logs.read_json(path or RESEARCH_FILE, "The researched cooking file")
    return data if isinstance(data, dict) else {}


def pools(recipes) -> list[tuple[str, tuple[tuple[str, ...], ...]]]:
    """Fold the recipes of one dish into ingredient pools: [(kind, pools)], where kind is "one" (any one ingredient of
    the pool), "two" (any two ingredients out of the pool, the same one twice included where the game allows it),
    "pair" (one of pool A + one of pool B) or "all" (three or more ingredients, one pool per ingredient). Ingredients
    with the same set of partners form one pool, so the fold is exact: every listed combination is a recipe."""
    out: list[tuple[str, tuple[tuple[str, ...], ...]]] = []
    singles = sorted({r.ingredients[0][0] for r in recipes if len(r.ingredients) == 1})
    if singles:
        out.append(("one", (tuple(singles),)))
    adjacency: dict[str, set[str]] = {}
    for r in recipes:
        if len(r.ingredients) == 2:
            a, b = r.ingredients[0][0], r.ingredients[1][0]
            adjacency.setdefault(a, set()).add(b)
            adjacency.setdefault(b, set()).add(a)
    if adjacency:
        groups: dict[frozenset, list[str]] = {}
        for ingredient, partners in adjacency.items():
            groups.setdefault(frozenset(partners), []).append(ingredient)
        members = sorted(tuple(sorted(g)) for g in groups.values())
        done = set()
        for pa in members:
            for pb in members:
                key = frozenset((pa, pb))
                if key in done or not (set(pb) & adjacency[pa[0]]):
                    continue
                done.add(key)
                out.append(("two", (pa,)) if pa == pb else ("pair", (pa, pb)))
    out += [("all", tuple((i,) for i, _ in r.ingredients)) for r in recipes if len(r.ingredients) >= 3]
    return out


def pool_text(entry: tuple[str, tuple[tuple[str, ...], ...]], label, alias: dict | None = None) -> str:
    """One folded entry as text: "A or B + C or D", "any two of: A or B" or "A + B + C". `alias` maps a pool (tuple of
    ids) to a letter that stands for it (fold_lines defines the letters once)."""
    kind, groups = entry
    alias = alias or {}

    def names(ids):
        if ids in alias:
            return f"pool {alias[ids]}"
        shown = " or ".join(label(i) for i in ids[:MAX_POOL_NAMES])
        return shown + (f" (+{len(ids) - MAX_POOL_NAMES} more)" if len(ids) > MAX_POOL_NAMES else "")
    if kind == "two":
        return f"any two of: {names(groups[0])}" if len(groups[0]) > 1 else f"2 x {names(groups[0])}"
    if kind == "one":
        return f"any one of: {names(groups[0])}" if len(groups[0]) > 1 else names(groups[0])
    return " + ".join(names(g) for g in groups)


def fold_lines(entries, label) -> list[str]:
    """The folded ingredient entries of one dish as lines. A pool that is long or used twice gets a letter and is
    spelled out once ("pool A = ..."), so a stew with 40 combinations stays a handful of lines."""
    uses = Counter(g for _, groups in entries for g in groups if len(g) > 1)
    lettered = [g for g, n in uses.items() if n > 1 or len(g) > 3]
    alias = {g: chr(ord("A") + k) for k, g in enumerate(sorted(lettered, key=lambda g: (-uses[g], g))[:12])}
    out = [f"pool {letter} = " + " or ".join(label(i) for i in g[:MAX_POOL_NAMES * 2])
           for g, letter in alias.items()]
    out += [pool_text(e, label, alias) for e in entries[:MAX_POOL_LINES + 4]]
    if len(entries) > MAX_POOL_LINES + 4:
        out.append(f"... and {len(entries) - MAX_POOL_LINES - 4} more combinations")
    return out


def dish_recipes(book, dish: str):
    """The Nutrient Processor recipes that make `dish`."""
    return [r for r in book.recipes if r.cooking and r.result == dish]


def dishes(book) -> set[str]:
    """Every dish the Nutrient Processor can make."""
    return {r.result for r in book.recipes if r.cooking}


def used_as_ingredient(book, item: str) -> dict[str, list]:
    """{dish: [recipes]} of the cooking recipes that use `item`."""
    out: dict[str, list] = {}
    for r in book.recipes:
        if r.cooking and any(i == item for i, _ in r.ingredients):
            out.setdefault(r.result, []).append(r)
    return out


def cookable(book, have: dict[str, int], value_of) -> list[dict]:
    """The dishes you can cook with what you hold, best base value first: [{dish, value, times, recipe}].
    `have` = {item id: amount}; `times` = how often the best matching recipe can run; one entry per dish (the recipe
    that can be run most often)."""
    best: dict[str, dict] = {}
    for r in book.recipes:
        if not r.cooking:
            continue
        need = Counter()
        for item, amount in r.ingredients:
            need[item] += amount
        if not all(have.get(item, 0) >= amount for item, amount in need.items()):
            continue
        times = min(have[item] // amount for item, amount in need.items())
        entry = best.get(r.result)
        if entry is None or times > entry["times"]:
            best[r.result] = {"dish": r.result, "value": value_of(r.result) or 0, "times": times, "recipe": r}
    return sorted(best.values(), key=lambda e: (-e["value"], e["dish"]))


def missing_for(recipe, have: dict[str, int]) -> list[str]:
    """Ingredient ids of a recipe you do not hold (enough of)."""
    need = Counter()
    for item, amount in recipe.ingredients:
        need[item] += amount
    return [i for i, a in need.items() if have.get(i, 0) < a]


def _fmt(n) -> str:
    return f"{int(n):,}"


@dataclass
class CookingView:
    """What a cooking answer is built from: the recipe book, what the player holds ({item id: amount}), `label(id)`
    = display name, `value_of(id)` = base value or None, and the researched facts."""
    book: object
    have: dict[str, int]
    label: Callable[[str], str]
    value_of: Callable[[str], int | None]
    research: dict = field(default_factory=dict)

    def value(self, item: str) -> int:
        return self.value_of(item) or 0


def _how_to_cook_lines(view: CookingView, dish: str) -> list[str]:
    """One dish: its value, its ingredient combinations folded into pools, and what the player can cook it with now."""
    recs = dish_recipes(view.book, dish)
    value = view.value_of(dish)
    out = [f"  How to cook {view.label(dish)} - base value {_fmt(value) + ' units each' if value else 'unknown'}; "
           f"{len(recs)} ingredient combinations, folded:"]
    out += [f"    {line}" for line in fold_lines(pools(recs), view.label)]
    can = [r for r in recs if not missing_for(r, view.have)]
    out.append("    you can cook it now with: " + (
        "; ".join(" + ".join(view.label(i) for i, _ in r.ingredients) for r in can[:3]) if can
        else "nothing you hold (no combination is complete)"))
    return out


def _used_in_lines(view: CookingView, item: str) -> list[str]:
    """One ingredient: the dishes it goes into, the most valuable first, each with its partners."""
    uses = used_as_ingredient(view.book, item)
    out = [f"  {view.label(item)} is an ingredient of {len(uses)} dishes; the most valuable:"]
    for dish in sorted(uses, key=lambda d: -view.value(d))[:MAX_DISHES]:
        partners = sorted({view.label(i) for r in uses[dish] for i, _ in r.ingredients if i != item})
        out.append(f"    {view.label(dish)} ({_fmt(view.value(dish))} units each) with "
                   + (" or ".join(partners[:MAX_POOL_NAMES]) or f"a second {view.label(item)}"))
    return out


def _cookable_now_lines(view: CookingView, cheapest: bool) -> list[str]:
    """The dishes the player can cook with what they hold: the best one, the others, and - when asked - the cheapest."""
    now = cookable(view.book, view.have, view.value_of)
    if not now:
        return ["  With what you hold you cannot complete any Nutrient Processor recipe right now (cooking "
                "needs raw ingredients such as vegetables, meat, eggs, milk or fish)."]
    out = [f"  Best dish you can cook right now: {_dish_now(now[0], view.label)}."]
    rest = now[1:MAX_DISHES]
    if rest:
        out.append(f"  The other {len(now) - 1} dishes you can cook right now (best first; shown {len(rest)}): "
                   + "; ".join(_dish_now(e, view.label) for e in rest))
    if cheapest:
        cheap = [e for e in reversed(now) if e["value"]][:3]
        out.append(f"  The cheapest dishes you can cook right now (of {len(now)}; cheapest first): "
                   + "; ".join(_dish_now(e, view.label) for e in cheap))
    return out


def _most_valuable_lines(view: CookingView) -> list[str]:
    """The most valuable dishes of the game, each with its easiest recipe and what the player still lacks."""
    ranked = sorted(dishes(view.book), key=lambda d: (-view.value(d), d))      # a stable order for equal values
    described = []
    for dish in ranked[:MAX_DISHES - 2]:
        easiest = min(dish_recipes(view.book, dish), key=lambda r: len(missing_for(r, view.have)))
        gap = missing_for(easiest, view.have)
        described.append(f"{view.label(dish)}: {_fmt(view.value(dish))} units each - e.g. "
                         f"{' + '.join(view.label(i) for i, _ in easiest.ingredients)}"
                         + (f" (you lack {', '.join(view.label(i) for i in gap)})" if gap else " (you can cook it now)"))
    return [f"  The most valuable dish in the game is {described[0]}",
            "  Next most valuable dishes: " + "; ".join(described[1:])]


def cooking_lines(view: CookingView, question: str, named_items: list[str],
                  edible_ids: set[str] | None = None) -> list[str]:
    """The persona's block for a cooking question (empty when it is not one).

    `named_items` = items the question names (matched by the caller), `edible_ids` = ids of edible products (a named
    dish only counts when it is one)."""
    book = view.book
    if book is None or not book.recipes:
        return []
    words = set(re.findall(r"[\w'-]+", (question or "").lower()))
    all_dishes = dishes(book)
    cooking_asked = bool(words & COOKING_WORDS)
    # A named dish makes it a cooking question when the question asks how/with what ("How do I make Fibrous Stew?");
    # a named ingredient only with a cooking word - "Sweetroot" alone is a question about the item.
    dish_named = [i for i in named_items if i in all_dishes and (edible_ids is None or i in edible_ids)]
    ingredient_named = [i for i in named_items if i not in all_dishes and used_as_ingredient(book, i)]
    named = dish_named + (ingredient_named if cooking_asked else [])
    if not (cooking_asked or (dish_named and words & HOW_WORDS)):
        return []
    out = ["Cooking (the Nutrient Processor; recipes from the game's own recipe table, every recipe uses 1 of each "
           "ingredient and makes 1 dish):"]
    out += [f"  {fact}" for fact in (view.research.get("facts") or [])[:3]]
    for item in named[:MAX_NAMED]:
        out += _how_to_cook_lines(view, item) if item in all_dishes else _used_in_lines(view, item)
    if not named or words & (GOOD_WORDS | NOW_WORDS | LOW_WORDS):
        out += _cookable_now_lines(view, cheapest=bool(words & LOW_WORDS))
        if not named:
            out += _most_valuable_lines(view)
    return out


def _dish_now(entry: dict, label) -> str:
    """"Furball Jelly: 9,000 each, up to 4 times - Leopard-Fruit + Processed Sugar" for one cookable dish."""
    r = entry["recipe"]
    times = entry["times"]
    return (f"{label(entry['dish'])}: {_fmt(entry['value'])} units each, up to {times} time"
            f"{'s' if times != 1 else ''} ({_fmt(entry['value'] * times)} units in all) - "
            f"{' + '.join(label(i) for i, _ in r.ingredients)}")
