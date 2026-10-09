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

Improved after the chat of 2026-10-05 (session 72389932): "what is in my ship inventory?" only got stack counts -
a question naming a place (ship, exosuit, freighter, storage container N) now gets that inventory's contents;
"what trade goods do I have?" found only "Suspicious Packet (Goods)" through the word "goods" - "trade goods"
(also "Handelsware", "trade commodities") now lists every trade good (ids TRA_*); and "where should I sell them?"
got nothing - each trade good now carries ``item_notes`` (which economies pay well and the nearest known system of
one, predicted ones marked).
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from .merging import is_merge_question, merge_lines

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
    "anzug", "haben", "kann", "finde", "finden", "brauche",
    # German filler and inflected place words ("sich" matched "Sich selbst reparierendes Heridium", "Containern"
    # the Storage Container items; chat of 2026-10-08, session cdee88f2) and English filler of a merge request:
    "sich", "mir", "mich", "aus", "die", "der", "das", "den", "dem", "des", "und", "oder", "werden", "wird", "können",
    "koennen", "lassen", "liessen", "ließen", "zusammen", "zusammengeführt", "zusammenführen", "zusammenfuehren",
    "zusammengefuehrt", "kombiniert", "kombinieren", "verschiedenen", "verschiedene", "gleiche", "gleichen",
    "containern", "behältern", "behaelter", "lagerbehälter", "lagern", "schiffen", "stapel",
    "different", "single", "combined", "combine", "merged", "merge", "present", "better", "sorting",
    # Filler of a request that is no item ("the best recipe I can execute right now" matched Liquidator Right Arm):
    "right", "left", "give", "best", "most", "worth", "value", "values", "cook", "cooking", "recipe", "recipes",
    "execute", "materials", "material", "currently", "right-now", "make", "made", "hold", "holding", "season",
    "seasons", "expedition", "expeditions", "dish", "dishes", "meal", "meals", "food", "today",
    "beste", "besten", "rezept", "rezepte", "kochen", "gericht", "gerichte", "wertvollste", "jetzt", "gerade",
    # Ordinals of a follow-up ("and the last one?" matched the poster "Built to Last", 2026-10-09):
    "first", "second", "third", "fourth", "last", "erste", "ersten", "zweite", "zweiten", "dritte", "dritten", "vierte",
    "vierten", "letzte", "letzten",
}
INVENTORY_WORDS = {"inventory", "inventories", "items", "inventar", "carry", "carrying", "storage", "lager", "haben",
                   "have", "own", "besitze"}
# Words naming an inventory -> which places (by the start of their name) a question means.
PLACE_WORDS = {
    "ship": ("Starship",), "starship": ("Starship",), "schiff": ("Starship",), "raumschiff": ("Starship",),
    "ships": ("Starship",), "starships": ("Starship",), "schiffe": ("Starship",), "raumschiffe": ("Starship",),
    "exosuit": ("Exosuit",), "suit": ("Exosuit",), "anzug": ("Exosuit",), "exo": ("Exosuit",),
    "freighter": ("Freighter",), "frachter": ("Freighter",),
    "storage": ("Storage Container", "Other storage"), "container": ("Storage Container",),
    "containers": ("Storage Container",), "lager": ("Storage Container", "Other storage"),
    "behälter": ("Storage Container",), "chest": ("Storage Container",),
    "containern": ("Storage Container",), "behältern": ("Storage Container",),
    "lagerbehälter": ("Storage Container",), "lagerbehältern": ("Storage Container",),
    "lagern": ("Storage Container", "Other storage"), "schiffen": ("Starship",), "frachtern": ("Freighter",),
}
TRADE_GOODS_RE = re.compile(r"trade ?goods?|trade commodit|handelsware|handelsgüter|handelsgut|commodit", re.I)
CONTAINER_WORDS = {"container", "containers", "containern", "behälter", "behältern", "lagerbehälter", "lagerbehältern"}
MAX_PLACE_ROWS = 60
MAX_ITEMS = 12
TOP_STACKS = 25
NEAREST_PLANETS = 3


ELISION_RE = re.compile(r"\b(?:l|d|j|n|s|c|m|t|qu|dell|all|nell|sull|un)['\u2019]", re.I)


def _words(text: str) -> list[str]:
    """The lower-case words of a text; a French/Italian elision is cut off first ("l'ammoniac" -> "ammoniac")."""
    return [w.lower() for w in WORD_RE.findall(ELISION_RE.sub(" ", text or ""))]


def places(snap: dict) -> list[tuple[str, list]]:
    """(place name, rows) for every inventory of the snapshot, as the game names them."""
    out = [("Exosuit", snap.get("exosuit") or []), ("Exosuit cargo", snap.get("exosuit_cargo") or [])]
    for ship in snap.get("ships") or []:
        # Unnamed ships are told apart by their type (several are "(unnamed)").
        named = ship["name"] if ship.get("name") and ship["name"] != "(unnamed)" else f"unnamed {ship.get('class') or 'ship'}"
        out.append((f"Starship '{named}'" + (" (primary)" if ship.get("primary") else ""), ship.get("inventory") or []))
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


ITEM_ID_RE = re.compile(r"^[A-Za-z0-9_#-]{2,40}$")     # the save holds the odd corrupt id: left out


def holdings(snap: dict) -> dict[str, dict]:
    """{item id: {total, places: [(place, amount)]}} across every inventory."""
    out: dict[str, dict] = {}
    for place, rows in places(snap):
        for item_id, amount, _maximum in rows:
            if not ITEM_ID_RE.match(str(item_id)):
                continue
            entry = out.setdefault(item_id, {"total": 0, "places": []})
            entry["total"] += int(amount or 0)
            entry["places"].append((place, int(amount or 0)))
    return out


def match_items(question: str, candidates: dict[str, list[str]], whole_only: bool = False) -> list[str]:
    """Item ids the question names. `candidates` maps id -> its names (English, game language). A whole name in
    the question wins; else an item matches when a question word (>= MIN_WORD letters, no stopword) is one of the
    words of its name (also with a plural -s / -e / -en / -n dropped). With `whole_only`, only whole names when
    there are any ("cook Fibrous Stew" names that dish, not the forty other stews)."""
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
    if whole_only and whole:
        return list(dict.fromkeys(whole))
    return list(dict.fromkeys(whole + partial))


def _fmt(n: int) -> str:
    return f"{n:,}"


def places_asked(question: str, snap: dict) -> list[str]:
    """The inventories a question names: "ship" -> the starships (the primary one first), "storage container 3"
    -> that container only, "exosuit" -> exosuit and its cargo."""
    words = _words(question)
    wanted = set()
    for w in words:
        wanted.update(PLACE_WORDS.get(w, ()))
    if not wanted:
        return []
    if CONTAINER_WORDS & set(words):        # "storage containers" are the numbered containers, not the other storage
        wanted.discard("Other storage")
    # "ship" means the one you fly; "ships" all of them.
    primary_only = "Starship" in wanted and not ({"ships", "schiffe", "starships", "raumschiffe"} & set(words))
    numbers = {int(w) for w in words if w.isdigit() and int(w) < 10}
    out = []
    for place, rows in places(snap):
        if not rows or not any(place.startswith(p) for p in wanted):
            continue
        if primary_only and place.startswith("Starship") and "(primary)" not in place:
            continue
        if place.startswith("Storage Container") and numbers and not any(place.startswith(f"Storage Container {n}")
                                                                          and not place[len(f"Storage Container {n}"):][:1].isdigit()
                                                                          for n in numbers):
            continue
        out.append(place)
    out.sort(key=lambda p: (not p.startswith("Starship") or "(primary)" not in p,))
    return out


def trade_kinds(snap: dict, place_names: list[str] | None, value_of) -> list[dict]:
    """Trade goods grouped by kind (trade.category_of: Technology, Minerals, ...) over the given inventories (all
    when None): [{category, units, value, goods: [(id, amount)]}], the most valuable kind first. `value_of(id)` is
    the game's base value per unit (None when unknown: counts 0). Seen 2026-10-05: "what kind of trade goods do I
    have the most aboard my ship?" got the single largest stack - a kind is the sum of all its goods."""
    from .trade import category_of
    kinds: dict[str, dict] = {}
    for place, rows in places(snap):
        if place_names is not None and place not in place_names:
            continue
        for item_id, amount, _maximum in rows:
            category = category_of(item_id)
            if category is None or not amount:
                continue
            kind = kinds.setdefault(category, {"category": category, "units": 0, "value": 0, "goods": {}})
            kind["units"] += int(amount)
            kind["value"] += int(amount) * (value_of(item_id) or 0)
            kind["goods"][item_id] = kind["goods"].get(item_id, 0) + int(amount)
    out = sorted(kinds.values(), key=lambda k: (-k["value"], -k["units"]))
    for kind in out:
        kind["goods"] = sorted(kind["goods"].items(), key=lambda g: -g[1])
    return out


def value_note(unit, amount: int | None = None) -> str:
    """What an item is worth, in the game's base value: "base value 3,280 each, 9,840 for 3" - or that the game gives
    it none (`unit` 0: it cannot be sold) - or "" when the item is in no value table (unknown)."""
    if unit is None:
        return ""
    if not unit:
        return "no sell value (the game gives this item a base value of 0: it cannot be sold)"
    note = f"base value {_fmt(unit)} units each"
    if amount and amount > 1:
        note += f", {_fmt(unit * amount)} for your {_fmt(amount)}"
    return note + " (before an economy's price factor)"


WORTH_WORDS = {"worth", "value", "values", "valuable", "wert", "werte", "wertvoll", "wertvolle", "wertvollste",
               "wertvollsten", "sell", "sold", "selling", "verkaufen", "verkauft", "verkaufe", "price", "prices",
               "preis", "preise", "earn", "earnings", "richest", "reich", "units"}
WHOLE_WORDS = {"inventory", "inventories", "inventar", "everything", "all", "whole", "total", "overall", "entire",
               "gesamt", "alles", "ganze", "ganzes", "komplett", "storage", "stored", "carry", "carrying"}
MAX_WORTH_STACKS = 8


def inventory_worth(snap: dict | None, value_of, name_of) -> list[str]:
    """What the player's inventories are worth at the game's base value (units, before any economy's price factor):
    the total, per place, the most valuable stacks and how many stacks the game gives no sell value."""
    if not snap:
        return []
    total, stacks, unvalued, by_place, rows = 0, 0, 0, [], []
    for place, place_rows in places(snap):
        subtotal = 0
        for item_id, amount, _maximum in place_rows:
            if not ITEM_ID_RE.match(str(item_id)) or not isinstance(amount, int):
                continue
            stacks += 1
            unit = value_of(item_id)
            if unit:
                subtotal += unit * amount
                rows.append((unit * amount, item_id, amount, unit))
            else:
                unvalued += 1
        if subtotal:
            by_place.append((place, subtotal))
        total += subtotal
    if not stacks:
        return []
    out = ["Inventory worth at the game's base value (what the game says each unit is worth before an economy's "
           "price factor - stations pay more or less; not what the money in your save is):",
           f"  total {_fmt(total)} units over {stacks} stacks in all inventories; {unvalued} stacks have no sell value "
           f"(technology, building parts and other things the game cannot sell)"]
    if by_place:
        out.append("  by place: " + "; ".join(f"{p}: {_fmt(v)}" for p, v in sorted(by_place, key=lambda x: -x[1])))
    merged: dict[str, list] = {}
    for value, item_id, amount, unit in rows:
        entry = merged.setdefault(item_id, [0, 0, unit])
        entry[0] += value
        entry[1] += amount
    top = sorted(merged.items(), key=lambda kv: -kv[1][0])[:MAX_WORTH_STACKS]
    out.append("  most valuable items (all places together): " + "; ".join(
        f"{name_of(i)}: {_fmt(v)} ({_fmt(a)} x {_fmt(u)})" for i, (v, a, u) in top))
    return out


@dataclass
class ItemLookups:
    """What `build_context` needs to name and describe items (supplied by the connector, so the builder stays pure).

    `name_of(id)` -> display name; `names_of(id)` -> [English, local]; `all_names` = every item the game knows
    (id -> names); `planets_offering(id)` -> ["Planet (System, distance)", ...] or None; `item_notes(id)` -> a line
    for an item (where a trade good sells) or None; `kind_lines(place names or None)` -> lines on the trade goods
    grouped by kind (asked for every trade-goods question); `value_of(id)` -> base value, 0 = cannot be sold, None
    = unknown."""
    name_of: Callable[[str], str]
    names_of: Callable[[str], list[str]]
    all_names: dict[str, list[str]]
    planets_offering: Callable[[str], list[str] | None] | None = None
    item_notes: Callable[[str], str | None] | None = None
    kind_lines: Callable[[list[str] | None], list[str]] | None = None
    value_of: Callable[[str], int | None] | None = None


def _named_item_lines(item_id: str, entry: dict | None, lk: ItemLookups, noted: dict[str, str]) -> list[str]:
    """The lines of one item the question names: total and places (when owned), its value, where a trade good sells
    (once per kind: identical notes say 'sells like ...'), and the nearest planets offering it."""
    name = lk.name_of(item_id)
    if entry is None:
        out = [f"- {name} [{item_id}]: 0 - not in any of your inventories"]
    else:
        where = "; ".join(f"{place}: {_fmt(amount)}" for place, amount in entry["places"])
        out = [f"- {name} [{item_id}]: {_fmt(entry['total'])} in total - {where}"]
    worth = value_note(lk.value_of(item_id), entry["total"] if entry else None) if lk.value_of else ""
    if worth:
        out.append(f"  {worth}")
    note = lk.item_notes(item_id) if lk.item_notes and entry is not None else None
    if note and note in noted:
        out.append(f"  sells like {noted[note]} (above)")
    elif note:
        noted[note] = name
        out.append(f"  {note}")
    nearest = lk.planets_offering(item_id) if lk.planets_offering else None
    if nearest:
        out.append(f"  found on: {'; '.join(nearest[:NEAREST_PLANETS])}")
    return out


def _named_items_section(matched: list[str], missing: list[str], have: dict, lk: ItemLookups) -> list[str]:
    out = ["", "Items the question names (totals across all your inventories, as of the last save):"]
    noted: dict[str, str] = {}      # a trade good's sell note is the same for its whole kind: once each
    for item_id in matched[:MAX_ITEMS]:
        out += _named_item_lines(item_id, have[item_id], lk, noted)
    if len(matched) > MAX_ITEMS:
        out.append(f"- ... and {len(matched) - MAX_ITEMS} more items with these words in their names")
    for item_id in missing:
        out += _named_item_lines(item_id, None, lk, noted)
    return out


def _place_sections(asked: list[str], snap: dict, lk: ItemLookups) -> list[str]:
    out: list[str] = []
    for place, rows in places(snap):
        if place not in asked:
            continue
        out += ["", f"Contents of {place} ({len(rows)} stacks):"]
        for item_id, amount, _maximum in [r for r in rows if ITEM_ID_RE.match(str(r[0]))][:MAX_PLACE_ROWS]:
            note = lk.item_notes(item_id) if lk.item_notes and item_id.startswith("TRA_") else None
            out.append(f"- {lk.name_of(item_id)} [{item_id}]: {_fmt(int(amount or 0))}" + (f" - {note}" if note else ""))
    return out


def _largest_stacks(have: dict, lk: ItemLookups) -> list[str]:
    out = ["", f"Your largest stacks in all (top {TOP_STACKS}, totals across all inventories):"]
    for item_id, entry in sorted(have.items(), key=lambda kv: -kv[1]["total"])[:TOP_STACKS]:
        out.append(f"- {lk.name_of(item_id)} [{item_id}]: {_fmt(entry['total'])}")
    return out


# "Do I have X?" cues: only then is an item the player does not own worth a "0 - not in any inventory" line. A
# knowledge question ("difference between a Portable Refiner and a Large Refiner") got "Portable Refiner: 0" first.
OWNERSHIP_WORDS = {"much", "many", "have", "has", "had", "own", "owned", "count", "total", "left", "got", "stock",
                   "inventory", "inventories", "viel", "viele", "habe", "hab", "habt", "besitze", "besitzen", "wieviel",
                   "übrig", "bestand", "inventar", "vorrat", "noch"}
# "What is my most abundant resource?" / "what do I have most of?": the largest stacks answer it.
MOST_RE = re.compile(r"abundant|largest|biggest|most of|have (the )?most|most (common|plentiful)|am meisten|"
                     r"meisten|häufigst|haeufigst|größt|groesst", re.I)


def _missing_unless_knowledge(question: str, missing: list[str]) -> list[str]:
    """The unowned items a question names, only when it asks about owning or amounts (OWNERSHIP_WORDS)."""
    return missing if OWNERSHIP_WORDS & set(_words(question)) else []


def _wants_largest_stacks(question: str) -> bool:
    """True for an inventory question ("what is in my inventory?") or a most/largest question."""
    return bool(INVENTORY_WORDS & set(_words(question)) or MOST_RE.search(question or ""))


def _missing_items(question: str, have: dict, all_names: dict[str, list[str]]) -> list[str]:
    """Items the question names that the player does not have: whole names of every item the game knows (not word
    matches - too broad), at most five."""
    q_text = " " + " ".join(_words(question)) + " "
    return [i for i, names in all_names.items() if i not in have and any(
        len(n) >= MIN_WORD and f" {' '.join(_words(n))} " in q_text for n in names if n)][:5]


def _names_a_place(names: list[str]) -> bool:
    """True when every name of an item is made of place words only ('Storage Container', 'Lagerbehälter')."""
    return bool(names) and all(w in PLACE_WORDS for name in names for w in _words(name))


NEAR_MISS_CUTOFF = 0.84          # difflib ratio: "Aroniun" -> "Aronium" (0.86); at 0.8 "ersten" matched an emote item
NEAR_MISS_MIN = 6                # shorter words are too likely to be a different word
NEAR_MISS_MAX = 3
# Kept in the player state, not in an inventory (TECHFRAG_R is the item record named "Nanites").
CURRENCY_IDS = {"UNITS", "QUICKSILVER", "NANITES", "TECHFRAG_R"}
NEAR_MISS_SHORT_WORDS = 6        # up to this many words a message may name an item without any cue word
# Words that make a longer message an item question (amount, recipe, place of an item), English and German.
ITEM_QUESTION_WORDS = {
    "much", "many", "have", "has", "own", "owned", "count", "total", "recipe", "recipes", "craft", "make", "made",
    "create", "refine", "get", "find", "where", "obtain", "mine", "need", "merge", "viel", "viele", "habe", "hab",
    "besitze", "wieviel", "wo", "rezept", "rezepte", "herstellen", "stelle", "bekomme", "bekommen", "finden",
    "gewinnen", "brauche", "zusammenlegen", "zusammenführen",
}


FOLDS = (("ph", "f"), ("th", "t"), ("ck", "k"), ("ß", "ss"), ("ä", "a"), ("ö", "o"), ("ü", "u"), ("y", "i"),
         ("ie", "i"))
DOUBLE_RE = re.compile(r"(.)\1+")
PLURAL_ENDS = ("s", "n", "en", "e", "es")


def fold(word: str) -> str:
    """A word as it sounds rather than how it is spelt: 'Paraphinium' and 'Paraffinium' both become 'parafinium'
    (ph -> f, doubled letters single, y -> i, umlauts plain). Applied to question and item words alike."""
    word = word.lower()
    for a, b in FOLDS:
        word = word.replace(a, b)
    return DOUBLE_RE.sub(r"\1", word)


@dataclass
class _NameIndex:
    """The words of every item name (>= NEAR_MISS_MIN letters): as spelt, and folded -> item ids."""
    real: set[str]
    folded: dict[str, set[str]]
    whole: dict[str, set[str]]          # folded one-word names -> item ids (to pick among several)

    @classmethod
    def build(cls, all_names: dict[str, list[str]]) -> _NameIndex:
        real, folded, whole = set(), {}, {}
        for item_id, names in all_names.items():
            for name in filter(None, names):
                words = [w for w in _words(name) if len(w) >= NEAR_MISS_MIN]
                real.update(words)
                for w in words:
                    folded.setdefault(fold(w), set()).add(item_id)
                if len(_words(name)) == 1:
                    whole.setdefault(fold(name), set()).add(item_id)
        return cls(real, folded, whole)

    def pick(self, key: str) -> str | None:
        """The one item a folded name word means: the only item with it, or the one whose whole name it is."""
        ids = self.folded.get(key, set())
        if len(ids) != 1:
            ids = ids & self.whole.get(key, set())
        return next(iter(ids)) if len(ids) == 1 else None

    def closest(self, word: str) -> str | None:
        """The item a misspelt word means: same when folded (also without a plural ending), else the closest folded
        word (difflib ratio >= NEAR_MISS_CUTOFF), else the only word starting with it minus its last letter
        ('Paraphine' -> 'parafin...' -> Paraffinium; only for 7+ letters)."""
        key = fold(word)
        for k in (key, *(key.removesuffix(end) for end in PLURAL_ENDS)):
            if k in self.folded:
                return self.pick(k)
        # A typo keeps the first letter: "Dilithium" (no such item) is not a misspelt "Lithium" (chat test 2026-10-09).
        close = [k for k in difflib.get_close_matches(key, list(self.folded), n=3, cutoff=NEAR_MISS_CUTOFF)
                 if k[0] == key[0]]
        if close:
            return self.pick(close[0])
        stem = [k for k in self.folded if len(key) >= 7 and k.startswith(key[:-1])]
        return self.pick(stem[0]) if len(stem) == 1 else None


_index_cache: tuple = (None, 0, None)


def near_miss_items(question: str, all_names: dict[str, list[str]]) -> list[tuple[str, str]]:
    """[(question word, item id)] for words of the question that are no word of any item name but close to one
    ("wieviel Aroniun hab ich" -> Aronium, "Paraphinium" -> Paraffinium): the persona said 0 or "no data" for a
    typo before (2026-10-09). Only words of NEAR_MISS_MIN+ letters, no stopwords, at most NEAR_MISS_MAX words."""
    global _index_cache
    asked = set(_words(question))
    if len(asked) > NEAR_MISS_SHORT_WORDS and not asked & ITEM_QUESTION_WORDS:
        return []         # a long message with no item cue is no item question ("write a python function" -> Piston)
    if _index_cache[0] is not all_names or _index_cache[1] != len(all_names):    # ~50 ms to build: once per names
        _index_cache = (all_names, len(all_names), _NameIndex.build(all_names))
    index = _index_cache[2]
    out: list[tuple[str, str]] = []
    for word in dict.fromkeys(w for w in _words(question) if len(w) >= NEAR_MISS_MIN and w not in STOPWORDS):
        if word in index.real or any(word.removesuffix(end) in index.real for end in PLURAL_ENDS):
            continue                  # a real item word (or its plural): no typo
        item_id = index.closest(word)
        if item_id:
            out.append((word, item_id))
    return out[:NEAR_MISS_MAX]


def _near_miss_sections(question: str, have: dict, lookups: ItemLookups) -> tuple[list[str], list[str], list[str]]:
    """(notes saying how a misspelt word was read, owned item ids, other item ids) for `near_miss_items`."""
    near = near_miss_items(question, lookups.all_names)
    notes = [f'(The question word "{w}" was read as "{lookups.name_of(i)}" [{i}].)' for w, i in near]
    return notes, [i for _, i in near if i in have], [i for _, i in near if i not in have]


def _merge_section(question: str, snap: dict, lookups: ItemLookups, asked: list[str]) -> list[str]:
    """The stacks to merge in the inventories asked about (all when none is named) - the plugin finds the
    duplicates, the model only copies them; items the question names (also misspelt) are explained."""
    scope = [(p, [r for r in rows if ITEM_ID_RE.match(str(r[0]))]) for p, rows in places(snap) if not asked or p in asked]
    have = holdings(snap)
    named = set(match_items(question, {i: lookups.names_of(i) for i in have}))
    notes, owned, _other = _near_miss_sections(question, have, lookups) if not named else ([], [], [])
    out = merge_lines(scope, lookups.name_of, named | set(owned))
    return out[:1] + notes + out[1:] if notes else out


def _question_sections(question: str, snap: dict, lookups: ItemLookups) -> list[str]:
    """The part of the data that depends on the question: stacks to merge, or the trade goods by kind, the items the
    question names, the contents of a named inventory, or the largest stacks."""
    asked = places_asked(question, snap)
    if is_merge_question(question):
        return _merge_section(question, snap, lookups, asked)
    out: list[str] = []
    have = holdings(snap)
    matched = match_items(question, {item_id: lookups.names_of(item_id) for item_id in have})
    if TRADE_GOODS_RE.search(question or ""):
        matched = list(dict.fromkeys([i for i in have if i.startswith("TRA_")] + [m for m in matched if m.startswith("TRA_")]))
        lines = lookups.kind_lines(asked or None) if lookups.kind_lines else []
        if lines:
            out += [""] + lines
    missing = _missing_unless_knowledge(question, _missing_items(question, have, lookups.all_names))
    # Currencies are no inventory items: "how many units do I have?" said "UNITS: 0 - not in any inventory" beside
    # the real balance of the status line (chat test 2026-10-09).
    matched = [i for i in matched if i not in CURRENCY_IDS]
    missing = [i for i in missing if i not in CURRENCY_IDS]
    if asked:        # "Lagerbehälter" is the place and also the name of the Storage Container item: here, the place
        matched = [i for i in matched if not _names_a_place(lookups.names_of(i))]
        missing = [i for i in missing if not _names_a_place(lookups.all_names[i])]
    elif not (matched or missing):        # nothing named exactly: a misspelt item name ("Aroniun")
        notes, matched, missing = _near_miss_sections(question, have, lookups)
        out += [""] + notes if notes else []
    if matched or missing:
        out += _named_items_section(matched, missing, have, lookups)
    if asked:        # a named place always lists its contents - an item matched by chance must not replace them
        out += _place_sections(asked, snap, lookups)
    elif _wants_largest_stacks(question) and not (matched or missing):
        out += _largest_stacks(have, lookups)
    return out


def build_context(question: str, snap: dict | None, lookups: ItemLookups, status_lines: list[str],
                  extra_lines: list[str]) -> str:
    """The data text for one question: `status_lines` (ready-made), the sections the question asks for
    (`_question_sections`), then the inventory overview and `extra_lines` (ready-made)."""
    if not snap:
        return "No save has been read yet, so there is no game data."
    out = list(status_lines) + _question_sections(question, snap, lookups)
    counts = [(place, sum(1 for r in rows if ITEM_ID_RE.match(str(r[0])))) for place, rows in places(snap)]
    out += ["", "Inventories: " + "; ".join(f"{place} ({n} stacks)" for place, n in counts if n)
            + f". {len(holdings(snap))} different items in total."]
    return "\n".join(out + extra_lines)


def saved_text(iso: str | None) -> str:
    """'2026-10-05 13:21' in this computer's time zone, from the save's ISO time."""
    if not iso:
        return "unknown"
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso
