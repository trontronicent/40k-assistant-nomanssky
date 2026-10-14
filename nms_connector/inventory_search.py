"""Search across every inventory for the page (not the persona): "kupfer", "copper storage", "Handelsgüter" (pure).

Every stack of every inventory (``assistant.places``: exosuit and its cargo, every starship, the freighter, the
storage containers and other storage) is matched by the words of its item - id, English and local name, English
and local category - and of its place, so a place word narrows the search ("copper freighter"). The matching is the
planet search's (``planet_search.terms`` / ``term_matches``): case-insensitive, ß = ss, ä = ae, a search word
matches every word that starts with it or with its German stem, and every search word must match.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import assistant, planet_search

SEARCH_INVENTORY = "search_inventory"          # action: search every inventory (the Inventory tab's form)
RESULTS_ID = "inventory-search-results"        # the results table, focused after a search
FORM_ID = "inventory-search-form"
MAX_QUERY_CHARS = planet_search.MAX_QUERY_CHARS
MAX_ROWS = 500                                 # the app caps a table at 500 rows
MAX_TOTALS = 10                                # items named in the totals line

#: Extra words a place is found by, keyed by the first word of its name (the game's German words, and "ship").
PLACE_WORDS = {
    "Exosuit": "Exoanzug",
    "Starship": "ship ships Raumschiff Schiff",
    "Freighter": "Frachter",
    "Storage": "Lager Lagercontainer Speicher",
    "Other": "storage Lager",
}


@dataclass(frozen=True)
class Hit:
    """One matching stack: where it is and what the save says about it."""
    place: str
    item_id: str
    amount: int
    maximum: int | None


def place_words(place: str) -> set[str]:
    """The words a place is found by: its name and the PLACE_WORDS of its first word."""
    first = place.split(" ", 1)[0]
    return set(planet_search.words(f"{place} {PLACE_WORDS.get(first, '')}"))


def item_words(item_id: str, entry: dict) -> set[str]:
    """The words an item is found by: id, names and categories in English and the game's language."""
    parts = [item_id] + [entry.get(k) or "" for k in ("en", "local", "cat_en", "cat_local")]
    return set(planet_search.words(" ".join(str(p) for p in parts)))


def search(snap: dict | None, query: str, lookup) -> list[Hit]:
    """Every stack whose item and place words match every word of the query, biggest stack first.

    `lookup(item_id)` = GameData.lookup (None for an unknown id). Ranked rather than left in the
    inventories' order, because the table is cut at MAX_ROWS: "copper" should show the 581 in storage
    container 0, not whichever stack happens to sit in the first inventory."""
    wanted = planet_search.terms(query)
    if not snap or not wanted:
        return []
    hits = []
    for place, rows in assistant.places(snap):
        here = place_words(place)
        for item_id, amount, maximum in rows:
            if not assistant.ITEM_ID_RE.match(str(item_id)):
                continue
            found_by = here | item_words(str(item_id), lookup(item_id) or {})
            if all(planet_search.term_matches(t, found_by) for t in wanted):
                hits.append(Hit(place, str(item_id), int(amount or 0), maximum))
    return sorted(hits, key=lambda h: (-h.amount, h.item_id, h.place))


def totals(hits: list[Hit]) -> list[tuple[str, int, int]]:
    """(item id, total amount, number of places) per item, largest total first (ties by id)."""
    sums: dict[str, list[int]] = {}
    for hit in hits:
        entry = sums.setdefault(hit.item_id, [0, 0])
        entry[0] += hit.amount
        entry[1] += 1
    return sorted(((i, t, n) for i, (t, n) in sums.items()), key=lambda x: (-x[1], x[0]))


def total_value(hits: list[Hit], value_of) -> int:
    """What everything found is worth in units (base value x amount), 0 when no value is known.

    `value_of(item_id)` = the item's base value from the game files (GcProductData BaseValue), which
    the inventory tables already show per item - summing it answers "is this stash worth a trip?"."""
    return sum((value_of(hit.item_id) or 0) * hit.amount for hit in hits)


def totals_text(hits: list[Hit], name_of, value_of=None) -> str:
    """'12 stacks of 3 items, worth 1,200,000 units. Total: Copper 700 (2 places), ...'

    `name_of(item_id)` gives the shown name, `value_of(item_id)` the base value (optional: without it
    the line says nothing about worth)."""
    items = totals(hits)
    named = [f"{name_of(i)} {t:,}" + (f" ({n} places)" if n > 1 else "") for i, t, n in items[:MAX_TOTALS]]
    more = len(items) - MAX_TOTALS
    worth = total_value(hits, value_of) if value_of else 0
    return (f"{len(hits)} stack(s) of {len(items)} item(s)"
            + (f", worth {worth:,} units" if worth else "")
            + ". Total: " + ", ".join(named) + (f", +{more} more items." if more > 0 else "."))
