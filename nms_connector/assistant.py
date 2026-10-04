"""The chat data of the No Man's Sky plugin: what a persona needs to answer "how much copper do I have?".

The app calls ``NmsConnector.chat_context(question)`` before a reply of every persona that draws on this plugin
(``plugin_context``) and puts the text into the system prompt - so it works with every model, also on
llama.cpp, which drops tools. ``build_context`` is pure: it gets the snapshot and lookups, not the plugin.

What goes in, always: a short status (when the data was saved, currencies, where you are, the primary ship with
its warp range) and one line each for timers, settlements and the frigate expedition. Then, for the items the
question names - by their English name, their name in the game's language or their id, as a whole name ("copper")
or as a word of a longer one ("Activated Copper") - the total across every inventory with the amount per place,
and the nearest recorded planets that offer it. Items the question names that you do not have are reported as 0.
Without a named item, a question about your inventory gets the largest stacks in all.
"""

from __future__ import annotations

import re
from datetime import datetime

WORD_RE = re.compile(r"[\w'-]+", re.UNICODE)
MIN_WORD = 4                      # question words shorter than this never match by themselves
# Words of a question that name no item (English and German).
STOPWORDS = {
    "much", "many", "have", "where", "what", "which", "there", "would", "could", "about", "with", "from", "into",
    "your", "mine", "total", "item", "items", "inventory", "inventories", "show", "list", "tell", "does", "find",
    "need", "want", "they", "them", "this", "that", "some", "more", "less", "each", "every", "please", "count",
    "stack", "stacks", "storage", "container", "containers", "ship", "ships", "starship", "freighter", "exosuit",
    "viel", "viele", "habe", "habt", "wieviel", "wo", "welche", "welcher", "meine", "mein", "insgesamt", "alle",
    "gibt", "noch", "auch", "bitte", "zeig", "zeige", "liste", "inventar", "lager", "frachter", "raumschiff",
    "anzug", "habe", "haben", "kann", "finde", "finden", "brauche",
}
INVENTORY_WORDS = {"inventory", "inventories", "items", "inventar", "carry", "carrying", "storage", "lager", "haben",
                   "have", "own", "besitze"}
MAX_ITEMS = 12
TOP_STACKS = 25
NEAREST_PLANETS = 3


def _words(text: str) -> list[str]:
    return [w.lower() for w in WORD_RE.findall(text or "")]


def places(snap: dict) -> list[tuple[str, list]]:
    """(place name, rows) for every inventory of the snapshot, as the game names them."""
    out = [("Exosuit", snap.get("exosuit") or []), ("Exosuit cargo", snap.get("exosuit_cargo") or [])]
    for ship in snap.get("ships") or []:
        out.append((f"Starship '{ship['name']}'" + (" (primary)" if ship.get("primary") else ""), ship.get("inventory") or []))
    freighter = snap.get("freighter") or {}
    out.append((f"Freighter '{freighter['name']}'" if freighter.get("name") else "Freighter", freighter.get("inventory") or []))
    for chest in snap.get("storage") or []:
        if chest.get("number") is not None:
            name = f"Storage Container {chest['number']}" + (f" ({chest['name']})" if chest.get("name") and not
                                                              str(chest["name"]).startswith("BLD_") else "")
        else:
            name = f"Other storage ({str(chest.get('key', '')).removesuffix('Inventory')})"
        out.append((name, chest.get("rows") or []))
    return out


def holdings(snap: dict) -> dict[str, dict]:
    """{item id: {total, places: [(place, amount)]}} across every inventory."""
    out: dict[str, dict] = {}
    for place, rows in places(snap):
        for item_id, amount, _maximum in rows:
            entry = out.setdefault(item_id, {"total": 0, "places": []})
            entry["total"] += int(amount or 0)
            entry["places"].append((place, int(amount or 0)))
    return out


def match_items(question: str, candidates: dict[str, list[str]]) -> list[str]:
    """Item ids the question names. `candidates` maps id -> its names (English, game language). A whole name in
    the question wins; else an item matches when a question word (>= MIN_WORD letters, no stopword) is one of the
    words of its name (also with a plural -s / -e / -en / -n dropped)."""
    q_words = _words(question)
    q_text = " " + " ".join(q_words) + " "
    keys = {w for w in q_words if len(w) >= MIN_WORD and w not in STOPWORDS}
    keys |= {w[:-len(end)] for w in set(keys) for end in ("en", "es", "s", "e", "n")
             if w.endswith(end) and len(w) - len(end) >= MIN_WORD}
    whole, partial = [], []
    for item_id, names in candidates.items():
        for name in names + [item_id]:
            n_words = _words(name)
            if not n_words:
                continue
            if len(" ".join(n_words)) >= MIN_WORD and f" {' '.join(n_words)} " in q_text:
                whole.append(item_id)
                break
            if keys & set(n_words):
                partial.append(item_id)
                break
    return list(dict.fromkeys(whole + partial))


def _fmt(n: int) -> str:
    return f"{n:,}"


def build_context(question: str, snap: dict | None, name_of, names_of, all_names: dict[str, list[str]],
                  status_lines: list[str], extra_lines: list[str], planets_offering=None) -> str:
    """The data text for one question. `name_of(id)` -> display name, `names_of(id)` -> [English, local],
    `all_names` = every item the game knows (id -> names), `status_lines`/`extra_lines` ready-made lines,
    `planets_offering(id)` -> ["Planet (System, distance)", ...] or None."""
    if not snap:
        return "No save has been read yet, so there is no game data."
    out = list(status_lines)
    have = holdings(snap)
    owned_names = {item_id: names_of(item_id) for item_id in have}
    matched = match_items(question, owned_names)
    # Named items you do not have: whole names of every item the game knows (not word matches - too broad).
    q_text = " " + " ".join(_words(question)) + " "
    missing = [i for i, names in all_names.items() if i not in have and any(
        len(n) >= MIN_WORD and f" {' '.join(_words(n))} " in q_text for n in names if n)][:5]
    if matched or missing:
        out.append("")
        out.append("Items the question names (totals across all your inventories, as of the last save):")
        for item_id in matched[:MAX_ITEMS]:
            entry = have[item_id]
            where = "; ".join(f"{place}: {_fmt(amount)}" for place, amount in entry["places"])
            out.append(f"- {name_of(item_id)} [{item_id}]: {_fmt(entry['total'])} in total - {where}")
            nearest = planets_offering(item_id) if planets_offering else None
            if nearest:
                out.append(f"  found on: {'; '.join(nearest[:NEAREST_PLANETS])}")
        if len(matched) > MAX_ITEMS:
            out.append(f"- ... and {len(matched) - MAX_ITEMS} more items with these words in their names")
        for item_id in missing:
            out.append(f"- {name_of(item_id)} [{item_id}]: 0 - not in any of your inventories")
            nearest = planets_offering(item_id) if planets_offering else None
            if nearest:
                out.append(f"  found on: {'; '.join(nearest[:NEAREST_PLANETS])}")
    elif INVENTORY_WORDS & set(_words(question)):
        out.append("")
        out.append(f"Your largest stacks in all (top {TOP_STACKS}, totals across all inventories):")
        for item_id, entry in sorted(have.items(), key=lambda kv: -kv[1]["total"])[:TOP_STACKS]:
            out.append(f"- {name_of(item_id)} [{item_id}]: {_fmt(entry['total'])}")
    out.append("")
    out.append("Inventories: " + "; ".join(f"{place} ({len(rows)} stacks)" for place, rows in places(snap) if rows))
    out += extra_lines
    return "\n".join(out)


def saved_text(iso: str | None) -> str:
    """'2026-10-05 13:21' in this computer's time zone, from the save's ISO time."""
    if not iso:
        return "unknown"
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso
