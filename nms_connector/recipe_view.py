"""The recipe viewer: search an item by name and see every recipe that makes it, drawn as a diagram (pure).

The chat already draws the recipes of a *question* (``diagrams.py``, app 3.17.0). This module is the same data
without a model: the player types an item name into a search box and the host draws the diagrams. One builder for
all four places, because the data is identical and only the drawing differs:

* the app's plugin page and the standalone page - ``sections(...)``, a ``recipes`` section per item (the host says
  whether it can draw that type; a host that cannot gets the recipe *lines* as a ``list`` section instead, so the
  viewer works on an older app too);
* the app's desktop overlay and the standalone overlay - ``overlay_area(...)``, one area with the same diagram
  data plus ``lines`` as the fallback, and ``search: True`` so the overlay offers its own query box.

**The language follows what was typed** (``language_of``): the game's language when the search words match the
local names ("Ferritstaub"), English when they match the English ones ("ferrite"), and for German also on the
question words alone ("wie mache ich ..."). The names in the diagrams, the station and the headings then all use
that one language - the player gets the names they see in their own game.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import diagrams, planet_search, recipes

SEARCH_RECIPES = "search_recipes"          # action: search the recipes (the Recipes tab's form, the overlay's box)
FORM_ID = "recipe-search-form"
RESULTS_ID = "recipe-search-results"       # the first result section, focused after a search
SECTION_TYPE = "recipes"                   # the view section type that draws diagrams (app 3.19.0)
OVERLAY_AREA = "recipes"

MAX_QUERY_CHARS = 60
MAX_HITS = 4                               # items one search answers with
MAX_MADE = 8                               # recipes that make one item
MAX_USED_IN = 6                            # recipes that use one item
MAX_OVERLAY_RECIPES = 4                    # the overlay window is small; the page shows them all
MAX_OVERLAY_LINES = 6

#: The viewer's own headings, per language (the game's words for the stations come from game_terms).
HEADINGS = {
    recipes.ENGLISH: {"made": "How to get {name}", "used": "{name} is used in", "value": "Base value",
                      "category": "Category", "about": "What it is", "none": "{name} has no recipe: it is gathered, "
                      "mined or bought.", "units": "units"},
    "german": {"made": "So bekommst du {name}", "used": "{name} wird gebraucht für", "value": "Grundwert",
               "category": "Kategorie", "about": "Was es ist", "none": "{name} hat kein Rezept: es wird gesammelt, "
               "abgebaut oder gekauft.", "units": "Units"},
}


def heading(key: str, language: str, **values) -> str:
    """One of the viewer's own headings in `language` (English for every language but German)."""
    texts = HEADINGS.get(language) or HEADINGS[recipes.ENGLISH]
    return texts.get(key, HEADINGS[recipes.ENGLISH][key]).format(**values)


def name_words(name: str | None) -> set[str]:
    """The words one name is found by, plus the whole name as a single word when the game writes it with
    separators: 'Warp-Zelle' -> {'warp', 'zelle', 'warpzelle'}.

    A German compound is one word to the player, and the game hyphenates a great many of them. Without this a
    search for "Warpzelle" matched nothing at all, while "warp zelle" and "warp cell" both worked (measured on
    the real item database, 2026-10-18).
    """
    parts = planet_search.words(name)
    joined = "".join(parts)
    return set(parts) | ({joined} if len(parts) > 1 else set())


def item_words(item_id: str, entry: dict, alt: list[str]) -> set[str]:
    """The words an item is found by: its id and its names in English, the game's language and ALT_LANGUAGES."""
    found = set(planet_search.words(item_id))
    for name in [entry.get("en"), entry.get("local"), *alt]:
        found |= name_words(str(name) if name else "")
    return found


def _rank(item: str, entry: dict, folded: str) -> tuple:
    """Sort key: a name the query spells out first, then one it starts, then the shortest name, then the id."""
    names = [planet_search.fold(n) for n in (entry.get("en"), entry.get("local")) if n]
    return (0 if folded in names else 1,
            0 if any(n.startswith(folded) for n in names) else 1,
            min((len(n) for n in names), default=999), item)


def search(book, lookup, query: str, alt_of=None) -> list[str]:
    """The items of the recipe book whose words match every word of `query`, best match first (<= MAX_HITS).

    Matching is the planet search's, so the player may type loosely and in either language ("ferrit", "chrom");
    `alt_of(item)` adds the other game languages when the host has read them."""
    wanted = planet_search.terms(query)
    if book is None or not wanted:
        return []
    folded = planet_search.fold(query).strip()
    found = []
    # The substances too, not only `items()`: a raw material that no recipe makes or uses would otherwise not be
    # searchable at all, and "where does Copper come from" is exactly what a player types into this box.
    for item in book.items() | book.substances:
        entry = lookup(item) or {}
        if not (entry.get("en") or entry.get("local")):
            continue                        # an id the game never names: nothing to search for and nothing to show
        found_by = item_words(item, entry, alt_of(item) if alt_of else [])
        if all(planet_search.term_matches(term, found_by) for term in wanted):
            found.append((_rank(item, entry, folded), item))
    return [item for _, item in sorted(found)][:MAX_HITS]


def _votes(query: str, hits: list[str], lookup, exact: bool) -> tuple[int, int]:
    """(words only a local name has, words only an English name has) over the found items.

    With `exact` a search word has to *be* a word of the name, else it may also start one. Both passes are
    needed: "ammonia" starts "Ammoniak" as well, so on prefixes alone an English search for an item whose
    German name is the English one plus an ending would look undecided (measured on the real item database,
    2026-10-18: ammonia/Ammoniak, ferrit/Ferritstaub).
    """
    local = english = 0
    for term in planet_search.terms(query):
        for item in hits:
            entry = lookup(item) or {}
            in_local = _has(term, entry.get("local"), exact)
            in_english = _has(term, entry.get("en"), exact)
            local += in_local and not in_english
            english += in_english and not in_local
    return local, english


def _has(term: str, name: str | None, exact: bool) -> bool:
    """Whether `name` holds the search word - as a whole word, or (not `exact`) as the start of one.

    The same words the search matches (`name_words`), so a hyphenated compound typed as one word decides the
    language too: "Warpzelle" is German, although the game writes it "Warp-Zelle".
    """
    words = name_words(name or "")
    return term in words if exact else planet_search.term_matches(term, words)


def language_of(query: str, hits: list[str], lookup, game_language: str) -> str:
    """The language the viewer answers in: this is the whole automatic switch, and nothing else in the viewer
    decides a language.

    In order: an English game is always English; then the search words that name a found item in one language
    only - as whole words first, as word starts second; then, for German, the question words alone
    (`diagrams.GERMAN_HINTS`, as a chat question is read). With no signal at all - an id, a name both languages
    share - the **game's own language** wins: every name the player sees while playing is in it.
    """
    if not game_language or game_language in (recipes.ENGLISH, "usenglish"):
        return recipes.ENGLISH
    for exact in (True, False):
        local, english = _votes(query, hits, lookup, exact)
        if local != english:
            return game_language if local > english else recipes.ENGLISH
    return game_language


def made_diagrams(book, lookup, icon_name, item: str, language: str, terms) -> list[dict]:
    """Every recipe that makes `item`: refiner, Nutrient Processor and its crafting recipe (<= MAX_MADE)."""
    made = book.made_by(item) + book.made_by(item, cooking=True)
    out = [diagrams.recipe_diagram(lookup, icon_name, r, language, terms) for r in made]
    crafted = book.crafting.get(item)
    if crafted:
        out.append({"ingredients": [diagrams.item_card(lookup, icon_name, i, a, language) for i, a in crafted],
                    "result": diagrams.item_card(lookup, icon_name, item, 1, language)})
    return out[:MAX_MADE]


def used_by(book, item: str) -> list:
    """The recipes that use `item` as an ingredient, refiner first then cooking (<= MAX_USED_IN)."""
    uses = book.used_in(item)
    return (uses["refiner"] + uses["cooking"])[:MAX_USED_IN]


def recipe_lines(lookup, book, item: str, language: str, terms) -> list[str]:
    """The same recipes as plain lines, for a host that cannot draw the diagrams (and the overlay's fallback)."""
    made = book.made_by(item) + book.made_by(item, cooking=True)
    out = [recipes._line_in(lookup, r, language, terms) for r in made[:MAX_MADE]]
    crafted = book.crafting.get(item)
    if crafted:
        out.append(" + ".join(f"{a} {recipes.name_in(lookup, i, language)}" for i, a in crafted)
                   + f" → 1 {recipes.name_in(lookup, item, language)}")
    return out


def recipes_section(title: str, drawn: list[dict], lines: list[str], section_types, section_id=None) -> dict:
    """One block of recipes: the `recipes` section when the host draws that type, else the lines as a list.

    The host decides, not the plugin: `ctx.section_types` says what the page can render, so the viewer still
    works on an app (or a standalone host) from before the diagrams existed.
    """
    out: dict = {"title": title}
    if section_id:
        out["id"] = section_id
    if SECTION_TYPE in (section_types or ()):
        return {**out, "type": SECTION_TYPE, "recipes": drawn,
                "empty": "No recipe found for this item."}
    return {**out, "type": "list", "items": lines or ["No recipe found for this item."]}


def _about_section(entry: dict, item: str, language: str) -> dict:
    """What the item is: the game's own description, its base value and its category - the viewer's header."""
    local = language != recipes.ENGLISH
    items = []
    desc = entry.get("desc_local" if local else "desc_en") or entry.get("desc_en")
    if desc:
        items.append({"label": heading("about", language), "value": " ".join(desc.split())})
    value = entry.get("value")
    if value:
        items.append({"label": heading("value", language),
                      "value": f"{recipes.value_text(value, language)} {heading('units', language)}"})
    category = entry.get("cat_local" if local else "cat_en") or entry.get("cat_en")
    if category:
        items.append({"label": heading("category", language), "value": category})
    items.append({"label": "Id", "value": item})
    return {"type": "kv", "items": items}


@dataclass(frozen=True)
class Viewer:
    """What the viewer needs to answer one search: the recipe book, the item database, the game's terms and what
    the host can draw. One object instead of four parameters threaded through every builder (code-shape.md)."""
    book: object
    gamedata: object
    terms: object
    section_types: tuple = ()

    @property
    def lookup(self):
        return self.gamedata.lookup

    @property
    def icon_name(self):
        return self.gamedata.icon_name

    def hits(self, query: str) -> list[str]:
        return search(self.book, self.lookup, query, self.gamedata.alt_of)

    def language(self, query: str, hits: list[str]) -> str:
        return language_of(query, hits, self.lookup, getattr(self.terms, "language", recipes.ENGLISH))


def item_sections(v: Viewer, item: str, language: str, first: bool) -> list[dict]:
    """One found item: what it is, every recipe that makes it, and what it is used in."""
    name = recipes.name_in(v.lookup, item, language)
    results_id = RESULTS_ID if first else None
    out = [{**_about_section(v.lookup(item) or {}, item, language), "title": name}]
    made = made_diagrams(v.book, v.lookup, v.icon_name, item, language, v.terms)
    if made:
        out.append(recipes_section(heading("made", language, name=name), made,
                                   recipe_lines(v.lookup, v.book, item, language, v.terms),
                                   v.section_types, results_id))
    else:
        none = {"type": "text", "text": heading("none", language, name=name)}
        out.append({**none, "id": results_id} if results_id else none)
    used = used_by(v.book, item)
    if used:
        out.append(recipes_section(
            heading("used", language, name=name),
            [diagrams.recipe_diagram(v.lookup, v.icon_name, r, language, v.terms) for r in used],
            [recipes._line_in(v.lookup, r, language, v.terms) for r in used], v.section_types))
    return out


def search_form(query: str) -> dict:
    """The viewer's search box - the one input of the whole feature, on both pages."""
    return {"type": "form", "id": FORM_ID, "title": "Find a recipe", "action": SEARCH_RECIPES,
            "submit_label": "Search",
            "description": "Type an item by name or id, in English or the game's language - loosely is enough "
                           "(\"chrom\", \"ferrit\"). Every recipe that makes it is drawn as a diagram, in the "
                           "language you typed in. An empty search clears it.",
            "fields": [{"id": "query", "label": "Item", "type": "text", "value": query,
                        "max_length": MAX_QUERY_CHARS, "placeholder": "e.g. Chromatic Metal",
                        "hint": "Words of the item's name or its id; the language follows what you type."}]}


def sections(book, gamedata, terms, query: str, section_types=()) -> list[dict]:
    """The Recipes tab: the search box and, for a query, every found item with its recipes."""
    out = [search_form(query)]
    if book is None or not book.recipes:
        error = f": {book.error}" if book is not None and book.error else "."
        return out + [{"type": "notice", "level": "warn",
                       "text": f"The recipes could not be read from the game files{error}"}]
    if not query:
        return out + [{"type": "text", "text": f"{len(book.recipes):,} refiner and Nutrient Processor recipes and "
                                               f"{len(book.crafting):,} crafting recipes are loaded. Search for an "
                                               f"item to see how it is made."}]
    v = Viewer(book, gamedata, terms, tuple(section_types or ()))
    hits = v.hits(query)
    if not hits:
        return out + [{"type": "text", "id": RESULTS_ID,
                       "text": f"No item matches every word of \"{query}\". Try fewer or shorter words."}]
    language = v.language(query, hits)
    for n, item in enumerate(hits):
        out += item_sections(v, item, language, first=n == 0)
    return out


def overlay_area(book, gamedata, terms, query: str) -> dict:
    """The overlay's *Recipes* area: the diagrams of the current query (<= MAX_OVERLAY_RECIPES) plus the same
    recipes as `lines`, which an overlay that cannot draw diagrams shows instead.

    `search: True` asks the overlay for its own query box; what it types runs SEARCH_RECIPES, so the page and the
    overlay share one query and one language decision.
    """
    # Shown at first (2026-10-18: it shipped off, and the search box was then nowhere to be found). The user
    # can untick it in the overlay's right-click menu, and the overlay remembers that.
    area = {"id": OVERLAY_AREA, "title": "Recipes", "default_on": True, "search": True,
            "query": query, "timers": [], "lines": [], "recipes": []}
    if book is None or not book.recipes:
        return {**area, "lines": ["The recipes could not be read from the game files."]}
    if not query:
        return {**area, "lines": ["Type an item name to see how it is made."]}
    v = Viewer(book, gamedata, terms)
    hits = v.hits(query)
    if not hits:
        return {**area, "lines": [f"Nothing matches \"{query}\"."]}
    language = v.language(query, hits)
    drawn, lines = [], []
    for item in hits:
        drawn += made_diagrams(book, v.lookup, v.icon_name, item, language, terms)
        lines += recipe_lines(v.lookup, book, item, language, terms) or [
            heading("none", language, name=recipes.name_in(v.lookup, item, language))]
    return {**area, "recipes": drawn[:MAX_OVERLAY_RECIPES], "lines": lines[:MAX_OVERLAY_LINES]}
