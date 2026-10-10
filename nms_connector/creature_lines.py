"""What the persona is told about companions and discoveries (pure; plugin 0.15.0).

The app cuts a plugin's data block at 8,000 characters and cuts from the end, so these blocks are short by
default and grow only for a question that asks for the detail:

* a question about **companions** (pet / egg / Begleiter / the arena / a pet's own name) gets one line per pet
  with trust, age, arena wins and harvest; the **abilities** with the game's description only when the question
  asks for them (abilities / moves / arena / battle), because five described moves per pet are ~600 characters;
* a question about **discoveries** (discovered / entdeckt / named / scanned) gets the counts, and the named
  records or the ones whose name contains the words of the question.

Both end with what is *not* known, so the model does not fill the gap: the egg cooldown and
species names are not in the game data, and record flags are not interpreted.
"""

from __future__ import annotations

import re

from . import pets
from .discoveries import KIND_LABELS, KIND_PLURALS, DiscoveryBook, matches
from .discoveries_view import day

PET_WORDS = {"pet", "pets", "companion", "companions", "egg", "eggs", "begleiter", "haustier", "haustiere",
             "ei", "eier", "hatch", "hatched", "trust", "vertrauen"}
BATTLE_WORDS = {"arena", "holo", "holo-arena", "xeno", "battle", "battles", "battler", "kampf", "kämpfe", "kaempfe",
                "league", "liga", "champion"}
ABILITY_WORDS = {"ability", "abilities", "move", "moves", "attack", "attacks", "skill", "skills", "fähigkeit",
                 "fähigkeiten", "faehigkeit", "faehigkeiten", "attacke", "attacken", "zug", "züge"}
DISCOVERY_WORDS = {"discovered", "discovery", "discoveries", "discover", "entdeckt", "entdeckung", "entdeckungen",
                   "entdecken", "scanned", "gescannt", "named", "renamed", "benannt", "umbenannt", "uploaded"}
KIND_WORDS = {"planet": "Planet", "planets": "Planet", "planeten": "Planet", "system": "SolarSystem",
              "systems": "SolarSystem", "systeme": "SolarSystem", "creature": "Animal", "creatures": "Animal",
              "fauna": "Animal", "tiere": "Animal", "plant": "Flora", "plants": "Flora", "flora": "Flora",
              "pflanzen": "Flora", "mineral": "Mineral", "minerals": "Mineral", "mineralien": "Mineral"}
# "name" alone is far too common (ship names, item names): it only opens the block next to one of these.
NAMING_WORDS = {"name", "names", "naming", "namen", "benenne", "benennen"}
NAMING_CONTEXT = {"did", "have", "ever", "already", "habe", "jemals", "schon", "hab"}
GENERIC = {"the", "and", "did", "have", "has", "what", "which", "how", "many", "much", "all", "any", "ever", "that",
           "this", "for", "with", "you", "your", "mine", "own", "wie", "viele", "habe", "ich", "meine", "meinen",
           "welche", "hast", "alle", "gibt", "was", "ist", "are", "was", "were"}
MAX_PET_LINES = 30
MAX_PET_CHARS = 3600
MAX_NAMED_LINES = 12
UNKNOWN_PETS = ("Not in the game data, so do not invent them: how long an egg takes to be ready, the species name the "
                "game shows for a creature.")
UNKNOWN_DISCOVERIES = ("Record flags are not interpreted (one of them marks records that came from other players). "
                       "There are no totals per planet, so there is no completion percentage.")


def _words(question: str) -> set[str]:
    return set(re.findall(r"[\w'-]+", (question or "").lower()))


def asks_pets(words: set[str], book_names: set[str] = frozenset()) -> bool:
    """A pet / egg / arena word, or the custom name of one of the player's own pets."""
    return bool(words & (PET_WORDS | BATTLE_WORDS)) or bool(words & book_names)


def asks_discoveries(words: set[str]) -> bool:
    """A discovery word, or 'name' next to a 'did I / have I / ever' word or a kind word ('did I name a planet')."""
    if words & DISCOVERY_WORDS:
        return True
    return bool(words & NAMING_WORDS) and bool(words & (NAMING_CONTEXT | set(KIND_WORDS)))


def _pet_line(pet: dict, book: pets.PetBook, now: float, with_moves: bool) -> str:
    age = pets.age_days(pet, now)
    parts = [pets.display_name(pet) + ":", f"{pet['id'].title() or '?'}", pet["type"] or "?", pet["biome"] or "?",
             f"trust {pets.trust_text(pet)}"]
    if age is not None:
        parts.append(f"{age} days old")
    parts.append(f"{pet['wins']} arena wins")
    if pet["traits"]:
        parts.append("personality: " + pets.personality_text(pet, book).replace(" / ", ", "))
    harvest = book.harvest(pet["id"])
    if harvest:
        products = " / ".join(harvest[k] for k in ("veg", "meat") if harvest.get(k))
        parts.append("harvest: " + " -> ".join(p for p in (harvest.get("action"), products) if p))
    line = "- " + parts[0] + " " + ", ".join(parts[1:])
    if with_moves:
        line += "; abilities: " + "; ".join(pets.move_lines(pet, book))
    elif pet["moves"]:
        line += f"; {len(pet['moves'])} abilities"
    return line


def pet_lines(question: str, snap: dict, book: pets.PetBook, now: float) -> list[str]:
    """The companions block for a question about them, or [] when it is about something else."""
    companions = (snap or {}).get("companions") or {}
    roster = companions.get("pets") or []
    eggs = companions.get("eggs") or []
    words = _words(question)
    names = {w for p in roster if p.get("name") for w in re.findall(r"[\w'-]{3,}", p["name"].lower())}
    if not (roster or eggs) or not asks_pets(words, names):
        return []
    unlocked, total = companions.get("slots") or [0, 0]
    out = [f"Companions: {len(roster)} (of {unlocked} unlocked slots), eggs {len(eggs)}, arena wins "
           f"{sum(p['wins'] for p in roster)}"]
    asked = (words & ABILITY_WORDS) or (words & BATTLE_WORDS)
    named = [p for p in roster if p.get("name") and words & set(re.findall(r"[\w'-]{3,}", p["name"].lower()))]
    shown = sorted(roster, key=lambda p: (-p["wins"], pets.display_name(p), p["ua"] or 0))
    budget = MAX_PET_CHARS
    for pet in shown[:MAX_PET_LINES]:
        line = _pet_line(pet, book, now, with_moves=bool(asked) and (not named or pet in named))
        if budget - len(line) < 0 and out[1:]:
            out.append(f"... and {len(roster) - len(out) + 1} more companions (ask about one by name).")
            break
        out.append(line)
        budget -= len(line)
    if eggs:
        kinds = {}
        for egg in eggs:
            kinds[egg["id"].title() or "?"] = kinds.get(egg["id"].title() or "?", 0) + 1
        out.append("Eggs: " + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
    out.append(UNKNOWN_PETS)
    return out


def discovery_lines(question: str, book: DiscoveryBook, label_of) -> list[str]:
    """The discoveries block for a question about them, or [] when it is about something else.
    `label_of(row)` names the place of a record (the system, and the planet when it has one)."""
    words = _words(question)
    if not book or not asks_discoveries(words):
        return []
    counts = book.counts(book.mine)
    out = ["Your discoveries: " + ", ".join(f"{n:,} {KIND_PLURALS.get(k, k).lower()}" for k, n in counts.items())
           + f" (plus {len(book.others):,} records from other players you came across)"]
    animals = [r for r in book.rows if r["k"] == "Animal"]
    if animals and not any(r["n"] for r in animals):
        out.append(f"None of the {len(animals)} creature records carries a name: creatures are not named in this save.")
    kinds = {KIND_WORDS[w] for w in words if w in KIND_WORDS}
    terms = sorted(w for w in words if len(w) >= 3 and w not in GENERIC and w not in DISCOVERY_WORDS
                   and w not in KIND_WORDS and w not in PET_WORDS and w not in NAMING_WORDS
                   and w not in NAMING_CONTEXT)
    # Filler words ("something") occur in no record name: only the question's words that do narrow the search.
    known = " ".join((r["n"] or "").casefold() for r in book.rows if r["n"])
    terms = [t for t in terms if t in known]
    found = matches(book, terms, kinds, MAX_NAMED_LINES) if (terms or kinds) else []
    named_only = [r for r in book.named()][:MAX_NAMED_LINES]
    if kinds and not found:      # "which planets did I name?" with none named: say so, do not list other kinds
        wanted = ", ".join(sorted(KIND_PLURALS.get(k, k).lower() for k in kinds))
        out.append(f"None of your {wanted} records carries a name.")
        shown = []
    else:
        shown = found or named_only
    if shown:
        out.append("Named records (newest first):")
        for r in shown:
            who = "by you" if r["m"] else f"by {r['o'] or 'another player'}"
            out.append(f"- {r['n']} ({KIND_LABELS.get(r['k'], r['k']).lower()}, {label_of(r)}, {day(r['t'])}, {who})")
    out.append(UNKNOWN_DISCOVERIES)
    return out
