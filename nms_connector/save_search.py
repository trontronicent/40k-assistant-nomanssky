"""One search box over everything read from the save: systems, planets, items, ships, bases, settlements,
discoveries and companions (pure).

The page already builds a table per kind, and each of those tables *is* the searchable text of its kind -
names in both languages, the game's own words for a biome or a weather, a portal address, an economy, a
guild. So this module searches the tables the page has already built (``groups_from_sections``) instead of
indexing the same data a second time: a row matches when every word of the query matches a word of one of
its cells, with the planet search's matching (``planet_search.terms`` / ``term_matches``: case-insensitive,
ß = ss, ä = ae, a search word matches longer words and German inflections).

Each kind's rows keep their own columns, their click target and their tooltips, so a hit stays as useful as
it is in its own tab - clicking a system still opens its map.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import planet_search

SEARCH_SAVE = "search_save"            # action: the Overview tab's one search box
FORM_ID = "save-search-form"
RESULTS_ID = "save-search-results"
MAX_QUERY_CHARS = planet_search.MAX_QUERY_CHARS
MAX_PER_GROUP = 25                     # rows shown per kind (the count says how many there are)
MAX_GROUPS = 8                         # kinds shown; the view's own section budget is 150


@dataclass
class Group:
    """One searchable kind: a table the page built, with what makes its rows clickable or right-clickable."""
    title: str
    columns: list
    rows: list
    keys: list | None = None
    row_action: str | None = None
    row_hint: str | None = None
    row_menu: list | None = None


@dataclass
class Found:
    """One kind's hits: the rows that matched, how many there were, and how to show them."""
    group: Group
    rows: list = field(default_factory=list)
    keys: list = field(default_factory=list)
    total: int = 0


# A row's words, kept by the row's own text. The page rebuilds its tables on every poll, so the same
# rows are folded again for every search; the same text always yields the same words, which makes this
# exact rather than a guess. Capped so a long session cannot grow it without bound (the whole page is
# about 10,000 rows, so the cap holds two full pages).
_WORDS: dict[str, frozenset] = {}
_WORDS_MAX = 20_000


def row_words(row: list) -> frozenset:
    """Every searchable word of a row - its cells' texts, icon cells by their text."""
    text = " ".join(planet_search.cell_text(c) for c in row)
    found = _WORDS.get(text)
    if found is None:
        if len(_WORDS) >= _WORDS_MAX:
            _WORDS.clear()
        found = _WORDS[text] = frozenset(planet_search.words(text))
    return found


def groups_from_sections(sections: list[dict], skip: tuple = ()) -> list[Group]:
    """The searchable groups of the page's own sections, tables inside (sub-)tabs included.

    `skip` names section ids to leave out - the search's own results table above all, which would
    otherwise be searched again on the next poll."""
    out = []
    for section in _walk(sections):
        if section.get("type") != "table" or section.get("id") in skip or not section.get("rows"):
            continue
        out.append(Group(title=section.get("title") or "Rows", columns=section.get("columns") or [],
                         rows=section["rows"], keys=section.get("row_keys"),
                         row_action=section.get("row_action"), row_hint=section.get("row_hint"),
                         row_menu=section.get("row_menu")))
    return out


def _walk(entries: list[dict]):
    """Every section, depth first: through `tabs` sections, and through a bare tab `{id, label, sections}`
    too - the page hands this its tabs, not a finished view."""
    for entry in entries or []:
        yield entry
        for tab in entry.get("tabs") or []:
            yield from _walk(tab.get("sections") or [])
        if "tabs" not in entry and entry.get("sections"):
            yield from _walk(entry["sections"])


def search(groups: list[Group], query: str, per_group: int = MAX_PER_GROUP) -> list[Found]:
    """Every kind with a matching row, most hits first; [] for a query that is only short words.

    A row matches when *every* search word matches one of its cells, as in the two older search
    fields - the words of one query belong together ("copper freighter", "toxic nitrogen")."""
    wanted = planet_search.terms(query)
    if not wanted or not groups:
        return []
    out = []
    for group in groups:
        found = Found(group=group)
        keys = group.keys or []
        for index, row in enumerate(group.rows):
            # One fold per row: this used to be inside the `all(...)`, so every search term folded the
            # whole row again (0.75 s for 10,112 rows on a real save, measured 2026-10-16).
            words = row_words(row)
            if all(planet_search.term_matches(t, words) for t in wanted):
                found.total += 1
                if len(found.rows) < per_group:
                    found.rows.append(row)
                    found.keys.append(keys[index] if index < len(keys) else None)
        if found.total:
            out.append(found)
    out.sort(key=lambda f: (-f.total, f.group.title))
    return out[:MAX_GROUPS]


def sections(results: list[Found], query: str) -> list[dict]:
    """The result tables, one per kind, each clickable exactly as it is in its own tab."""
    if not query:
        return []
    if not results:
        return [{"type": "notice", "id": RESULTS_ID, "level": "info", "text":
                 f"Nothing in your save matches every word of \"{query}\". Try fewer or shorter words - "
                 "a word also finds longer ones (\"kupf\" finds Kupfer), but all of them must match."}]
    out = []
    for index, found in enumerate(results):
        cut = f" - the first {len(found.rows)}" if len(found.rows) < found.total else ""
        table = {"type": "table", "title": f"{found.group.title}: {found.total} match(es){cut}",
                 "columns": found.group.columns, "rows": found.rows}
        if index == 0:
            table["id"] = RESULTS_ID            # the page scrolls to the first group after a search
        out.append(table | _row_handles(found))
    return out


def _row_handles(found: Found) -> dict:
    """What keeps a hit clickable (`row_action`) and right-clickable (`row_menu`, e.g. copying a ship or a
    container) as it was in its own table - nothing when its rows have no keys."""
    group = found.group
    if not any(k is not None for k in found.keys):
        return {}
    out: dict = {}
    if group.row_action:
        out.update(row_action=group.row_action, row_hint=group.row_hint or "Click a row to open it.")
    if group.row_menu:
        out["row_menu"] = group.row_menu
    return out | ({"row_keys": found.keys} if out else {})
    return out


def summary(results: list[Found], query: str) -> str:
    """'7 matches in 3 kinds: Visited systems 2, Planets ...' - the line above the result tables."""
    total = sum(f.total for f in results)
    named = ", ".join(f"{f.group.title} {f.total}" for f in results)
    return f"{total} match(es) for \"{query}\" in {len(results)} kind(s): {named}."
