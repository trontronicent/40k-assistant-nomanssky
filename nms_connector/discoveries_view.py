"""The *Discoveries* tab (plugin 0.15.0): what the save's discovery store holds, as declarative sections (pure)."""

from __future__ import annotations

from datetime import datetime

from . import planets_view
from .discoveries import KIND_LABELS, KIND_PLURALS, SCANNED_KINDS, DiscoveryBook, planet_of, system_of

MAX_SYSTEM_ROWS = 300
MAX_NAMED_ROWS = 200

INTRO = ("Everything the game recorded in your save: what you scanned, and the systems and planets you named. The "
         "record store also holds other players' discoveries you came across, so the counts below are split. "
         "Records carry a few flags (shown as the game stores them) whose meaning is not known, and a planet's "
         "record has no totals to compare against, so there is no completion percentage - only what you have found.")


def day(stamp: int | None) -> str:
    """'2026-10-09', or '–' without a time."""
    return datetime.fromtimestamp(stamp).strftime("%Y-%m-%d") if stamp else "–"


def place(row: dict, ctx) -> str:
    """'Aldrin Reach' for a system, 'Aldrin Reach, planet 2' for something on a planet."""
    system = planets_view._system_label(system_of(row), ctx.visit(system_of(row)))
    planet = planet_of(row)
    return f"{system}, planet {planet}" if planet else system


def stats_section(book: DiscoveryBook) -> dict:
    """The counts: your own per kind, other players' records, and how many carry a name."""
    mine = book.counts(book.mine)
    items = [{"label": KIND_PLURALS.get(kind, kind), "value": f"{count:,}"} for kind, count in mine.items()]
    items.append({"label": "Other players' records", "value": f"{len(book.others):,}"})
    items.append({"label": "Named by someone", "value": f"{len(book.named()):,}"})
    items.append({"label": "Your first record", "value": day(book.first_seen())})
    return {"type": "stats", "title": "Your discoveries", "items": items}


def systems_table(book: DiscoveryBook, ctx) -> dict:
    """Your scans per system, most scanned first; a click opens the system's map."""
    entries = [e for e in book.by_system() if e["scanned"] or e["named"]][:MAX_SYSTEM_ROWS]
    rows = [[planets_view._system_label(e["system"], ctx.visit(e["system"])), e["plants"], e["creatures"],
             e["minerals"], e["planets"], e["named"]] for e in entries]
    return {"type": "table", "id": "discoveries-by-system", "title": "Scans by system",
            "columns": ["System", "Plants", "Creatures", "Minerals", "Planets", "Named"],
            "rows": rows, "row_action": planets_view.OPEN_SYSTEM,
            "row_keys": [planets_view.system_key_text(e["system"]) for e in entries],
            "row_hint": "Click a system to show its star and planets in the map."}


def named_table(book: DiscoveryBook, ctx) -> dict:
    """Everything somebody named, newest first - also what other players named that you came across."""
    named = book.named()[:MAX_NAMED_ROWS]
    rows = []
    for r in named:
        who = "you" if r["m"] else (r["o"] or "another player")
        rows.append([r["n"], KIND_LABELS.get(r["k"], r["k"]), place(r, ctx), day(r["t"]), who])
    return {"type": "table", "id": "discoveries-named", "title": "Named discoveries",
            "columns": ["Name", "Kind", "Where", "When", "By"], "rows": rows,
            "row_hint": "Names a discoverer gave; creatures are never named in this save."}


def sections(snap: dict | None, ctx, book: DiscoveryBook) -> list[dict]:
    """The whole tab, or one note when no save has been read or the store is empty."""
    if not snap:
        return [{"type": "text", "text": "No save has been read yet: your discoveries appear once the connector has "
                                         "read a save file."}]
    if not book:
        return [{"type": "text", "text": "This save has no discovery records."}]
    scanned = sum(1 for r in book.mine if r["k"] in SCANNED_KINDS)
    return [{"type": "text", "text": INTRO}, stats_section(book),
            {"type": "kv", "title": "Scans", "items": [{"label": "Plants, creatures and minerals scanned by you",
                                                        "value": f"{scanned:,}"}]},
            systems_table(book, ctx), named_table(book, ctx)]
