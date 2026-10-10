"""The *Companions* tab (plugin 0.15.0): pets, eggs and creature-battle abilities as declarative sections (pure)."""

from __future__ import annotations

from . import pets, planets_view
from .discoveries import DiscoveryBook
from .discoveries_view import day, place
from .summary import system_key_of

INTRO = ("Your companions and eggs as the save holds them. Trait values, how long an egg takes to be ready and the "
         "species name the game shows are not stored in a readable form, so the traits are shown raw (three signed "
         "numbers) and no species name is made up. Abilities are the game's ability templates with its own "
         "description; the harvest is read from the game's text.")


def harvest_text(pet: dict, book: pets.PetBook) -> str:
    """'Collect Milk -> Fresh Milk / Raw Steak', only with the parts the game has; '–' for none."""
    found = book.harvest(pet["id"])
    if not found:
        return "–"
    products = " / ".join(found[k] for k in ("veg", "meat") if found.get(k))
    return " -> ".join(part for part in (found.get("action"), products) if part) or "–"


def origin_text(pet: dict, ctx) -> str:
    """The system the creature comes from (its origin address), or '–'."""
    key = system_key_of(pet["ua"]) if pet.get("ua") is not None else None
    return planets_view._system_label(key, ctx.visit(key)) if key is not None else "–"


def first_scan_text(pet: dict, animals: dict, ctx) -> str:
    """'2026-03-02, Aldrin Reach, planet 2' for the player's scan of this kind of creature, else '–'."""
    record = pets.first_scan(pet, animals)
    if record is None:
        return "–"
    who = "" if record["m"] else f" by {record['o'] or 'another player'}"
    return f"{day(record['t'])}, {place(record, ctx)}{who}"


def name_cell(pet: dict) -> dict:
    """The name, with the seeds and the stat classes in its tooltip."""
    seeds = pet["seeds"]
    hint = "\n".join([
        f"Stat classes: {pets.stat_classes_text(pet)}",
        f"Treats eaten: {' / '.join(str(v) for v in pet['treats']) or '–'} ({pet['treats_free']} to give)",
        f"Creature seed: {pets.pack_seed(seeds[0])}",
        f"Species seed: {pets.pack_seed(seeds[2])}",
        f"Genus seed: {pets.pack_seed(seeds[3])}",
    ])
    return {"text": pets.display_name(pet), "hint": hint}


def abilities_cell(pet: dict, book: pets.PetBook) -> dict:
    """'4 abilities', with each template and the game's description in its tooltip."""
    lines = pets.move_lines(pet, book)
    return {"text": f"{len(lines)}", "sort": len(lines), "hint": "\n".join(lines) or "No abilities in the save."}


def type_cell(pet: dict, book: pets.PetBook) -> dict:
    """The creature type with a tooltip saying what the game's wording for it means."""
    return {"text": pet["type"] or "?", "hint": pets.type_note(pet["type"], book)}


def traits_hint(book: pets.PetBook) -> str:
    """What the three personality numbers are: three signed values, and which words the game uses."""
    names = ", ".join(pets.trait_names(book))
    return chr(10).join([
        "Three personality values the save stores for this companion, signed (observed values lie between -1 and +1).",
        "",
        f"The game's personality words: {names}.",
        "",
        "Not confirmed: which value belongs to which word, and what a negative sign means. The save keeps three "
        "numbers and the game shows six words, so each value is most likely one axis between two opposite words. "
        "The plugin therefore shows the numbers as stored and does not name them.",
        "",
        "In the game a personality word is shown with a class from S (strongest) to C (weakest).",
    ])


def roster_table(companions: dict, book: pets.PetBook, animals: dict, ctx, now: float) -> dict:
    """One row per companion; wins and trust sort as numbers."""
    rows = []
    for pet in companions["pets"]:
        age = pets.age_days(pet, now)
        rows.append([
            name_cell(pet), pet["id"].title() or "?", type_cell(pet, book), pet["biome"] or "?",
            {"text": pets.trust_text(pet), "sort": pet["trust"]},
            {"text": "–" if age is None else f"{age:,}", "sort": age if age is not None else -1},
            {"text": f"{pet['wins']:,}", "sort": pet["wins"]}, abilities_cell(pet, book),
            harvest_text(pet, book), {"text": pets.traits_text(pet), "hint": traits_hint(book)},
            first_scan_text(pet, animals, ctx), origin_text(pet, ctx)])
    return {"type": "table", "id": "companions-roster", "title": "Companions",
            "columns": ["Name", "Creature", "Type", "Biome", "Trust", "Age (days)", "Arena wins", "Abilities",
                        "Harvest", "Personality (3 raw values)", "First scanned", "Origin"], "rows": rows}


def eggs_table(companions: dict, ctx, now: float) -> dict:
    """The eggs: what hatches from them is already decided by their creature."""
    rows = []
    for egg in companions["eggs"]:
        age = pets.age_days(egg, now)
        rows.append([egg["id"].title() or "?", egg["type"] or "?", egg["biome"] or "?",
                     {"text": pets.trust_text(egg), "sort": egg["trust"]},
                     {"text": "–" if age is None else f"{age:,}", "sort": age if age is not None else -1},
                     origin_text(egg, ctx)])
    return {"type": "table", "id": "companions-eggs", "title": "Eggs",
            "columns": ["Creature", "Type", "Biome", "Trust", "Age (days)", "Origin"], "rows": rows}


def stats_section(companions: dict) -> dict:
    """Slots, counts and the arena record."""
    unlocked, total = companions["slots"]
    named = sum(1 for p in companions["pets"] if p["name"])
    return {"type": "stats", "title": "Companions", "items": [
        {"label": "Companions", "value": f"{len(companions['pets'])} of {unlocked} unlocked slots"
         if total else str(len(companions["pets"]))},
        {"label": "Eggs", "value": str(len(companions["eggs"]))},
        {"label": "Named", "value": str(named)},
        {"label": "Arena wins (all)", "value": f"{sum(p['wins'] for p in companions['pets']):,}"},
    ]}


def sections(snap: dict | None, ctx, book: pets.PetBook, discoveries: DiscoveryBook, now: float) -> list[dict]:
    """The whole tab, or one note when there is no save or no companion."""
    if not snap:
        return [{"type": "text", "text": "No save has been read yet: your companions appear once the connector has "
                                         "read a save file."}]
    companions = snap.get("companions") or {"pets": [], "eggs": [], "slots": [0, 0]}
    if not companions["pets"] and not companions["eggs"]:
        return [{"type": "text", "text": "This save has no companions or eggs."}]
    out = [{"type": "text", "text": INTRO}, stats_section(companions)]
    if book.error:
        out.append({"type": "notice", "level": "info",
                    "text": f"Ability descriptions and harvest words are unavailable ({book.error})."})
    animals = discoveries.animal_by_seed()
    out.append(roster_table(companions, book, animals, ctx, now))
    if companions["eggs"]:
        out.append(eggs_table(companions, ctx, now))
    return out
