"""The *Companions* tab (plugin 0.15.0): pets, eggs and creature-battle abilities as declarative sections (pure)."""

from __future__ import annotations

from . import pets, planets_view
from .discoveries import DiscoveryBook
from .discoveries_view import day, place
from .summary import system_key_of

INTRO = ("Your companions and eggs as the save holds them, with when each egg can be hatched (24 h after it was "
         "laid) and when each companion can lay again. Trait values and the species name the game shows are not "
         "stored in a readable form, so the traits are shown raw (three signed "
         "numbers) and no species name is made up. The C/B/A/S tier of each battle stat is not in the save either "
         "- a tier decides how much benefit that stat gets from each treat, is fixed when a companion hatches, "
         "and no amount of training, gene editing or resizing changes it - so a companion's name shows the treats "
         "you have invested in each stat, which is investment rather than strength. "
         "Abilities are the game's ability templates with its own description; the harvest is read from the "
         "game's text.")


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
    """The name, with the treats invested in each battle stat and the seeds in its tooltip."""
    seeds = pet["seeds"]
    hint = "\n".join([
        f"Treats: {pets.treats_text(pet)} ({pet['treats_free']} to give)",
        "Each stat also has a C/B/A/S tier, which decides how much benefit it gets from every treat. Tiers are "
        "fixed when a companion hatches and the save does not hold them, so these numbers are what you have "
        "invested - not how strong the companion is.",
        f"Creature seed: {pets.pack_seed(seeds[0])}",
        f"Species seed: {pets.pack_seed(seeds[2])}",
        f"Genus seed: {pets.pack_seed(seeds[3])}",
    ])
    return {"text": pets.display_name(pet), "hint": hint}


def size_cell(pet: dict) -> dict:
    """'3.7 m', sorting by the real scale, with the weight the game shows in its tooltip."""
    return {"text": pets.size_text(pet), "sort": pet.get("scale") or 0.0,
            "hint": f"Weight: {pets.weight_text(pet)}\nBoth are what the game shows, from the save's stored "
                    f"scale ({pet.get('scale') or 0:.6f})."}


def abilities_cell(pet: dict, book: pets.PetBook) -> dict:
    """'4 abilities', with each template and the game's description in its tooltip."""
    lines = pets.move_lines(pet, book)
    return {"text": f"{len(lines)}", "sort": len(lines), "hint": "\n".join(lines) or "No abilities in the save."}


def type_cell(pet: dict, book: pets.PetBook) -> dict:
    """The creature type with a tooltip saying what the game's wording for it means."""
    return {"text": pet["type"] or "?", "hint": pets.type_note(pet["type"], book)}


def traits_hint(book: pets.PetBook, pet: dict) -> str:
    """What the three personality values are: one axis each, with the two words the game uses for its ends."""
    axes = [f"{book.trait_short.get(p) or pets.TRAIT_FALLBACK[p]} (+) / {book.trait_short.get(n) or pets.TRAIT_FALLBACK[n]} (-)"
            for p, n in pets.TRAIT_AXES]
    return chr(10).join([
        "Three personality values, one axis each. The sign says which end of the axis the companion leans to, the "
        "number is the percentage the game shows.",
        "",
        "Value 1: " + axes[0],
        "Value 2: " + axes[1],
        "Value 3: " + axes[2],
        "",
        "Read against companions whose values you gave from the game. Aggression as the positive end of value 2 is "
        "inferred (the only companions that lean that way are Predators); the other five words were confirmed.",
        "",
        "Stored values: " + pets.traits_text(pet),
    ])


def next_egg_cell(pet: dict, now: float) -> dict:
    """When this companion can lay again, the soonest sorting first, with what the save cannot see in its tooltip."""
    ready = pets.lay_at(pet)
    hint = "\n".join([
        "A companion lays its first egg at 28 days old (measured on the save), and after an egg the next induction "
        "can be started 24 h later (confirmed in the game). An egg still waiting to hatch does not hold the next "
        "one back - a companion can have several.",
        "The game also refuses an egg when it says: " + ", ".join(pets.LAY_BLOCKERS) + ". None of those are in the "
        "save, so if the time has come and no egg can be induced, feed it and take it to its own climate.",
    ])
    return {"text": pets.lay_text(pet, now), "sort": ready if ready is not None else 1 << 62, "hint": hint}


def roster_table(companions: dict, book: pets.PetBook, animals: dict, ctx, now: float) -> dict:
    """One row per companion; wins, trust and the next egg sort as numbers."""
    rows = []
    for pet in companions["pets"]:
        age = pets.age_days(pet, now)
        rows.append([
            name_cell(pet), pet["id"].title() or "?", type_cell(pet, book), pet["biome"] or "?",
            size_cell(pet), {"text": pets.trust_text(pet), "sort": pet["trust"]},
            {"text": "–" if age is None else f"{age:,}", "sort": age if age is not None else -1},
            next_egg_cell(pet, now),
            {"text": f"{pet['wins']:,}", "sort": pet["wins"]}, abilities_cell(pet, book),
            harvest_text(pet, book), {"text": pets.personality_text(pet, book), "hint": traits_hint(book, pet)},
            first_scan_text(pet, animals, ctx), origin_text(pet, ctx)])
    return {"type": "table", "id": "companions-roster", "title": "Companions",
            "columns": ["Name", "Creature", "Type", "Biome", "Size", "Trust", "Age (days)", "Next egg", "Arena wins",
                        "Abilities", "Harvest", "Personality", "First scanned", "Origin"], "rows": rows}


def hatch_cell(egg: dict, now: float) -> dict:
    """'Ready to hatch' or the wait left, the soonest sorting first, with when it was laid in its tooltip."""
    ready = pets.hatch_at(egg)
    hint = ("The save holds no laying time for this egg." if not egg.get("born") else
            f"Laid {pets.duration_text(now - egg['born'])} ago. An egg can be hatched 24 h after it was laid "
            f"(confirmed in the game).")
    return {"text": pets.hatch_text(egg, now), "sort": ready if ready is not None else 1 << 62, "hint": hint}


def parent_cell(egg: dict, roster: list[dict]) -> dict:
    """The companion the egg came from - the save keeps its parent's birth time in the egg's own LastEggTime."""
    parent = pets.parent_of(egg, roster)
    return {"text": pets.display_name(parent) if parent else "–",
            "hint": "An egg records its parent's birth time, which is how it is matched to a companion."
                    if parent else "No companion in this save matches this egg's parent."}


def eggs_table(companions: dict, ctx, now: float) -> dict:
    """The eggs: when each can be hatched, which companion laid it, and what it will become."""
    rows = []
    for egg in companions["eggs"]:
        age = pets.age_days(egg, now)
        rows.append([egg["id"].title() or "?", hatch_cell(egg, now), parent_cell(egg, companions["pets"]),
                     egg["type"] or "?", egg["biome"] or "?",
                     {"text": pets.trust_text(egg), "sort": egg["trust"]},
                     {"text": "–" if age is None else f"{age:,}", "sort": age if age is not None else -1},
                     origin_text(egg, ctx)])
    return {"type": "table", "id": "companions-eggs", "title": "Eggs",
            "columns": ["Creature", "Hatches", "Parent", "Type", "Biome", "Trust", "Age (days)", "Origin"],
            "rows": rows}


def stats_section(companions: dict, now: float) -> dict:
    """Slots, counts, what is waiting for you right now, and the arena record."""
    unlocked, total = companions["slots"]
    named = sum(1 for p in companions["pets"] if p["name"])
    hatchable = sum(1 for e in companions["eggs"] if (at := pets.hatch_at(e)) is not None and now >= at)
    can_lay = sum(1 for p in companions["pets"] if (at := pets.lay_at(p)) is not None and now >= at)
    return {"type": "stats", "title": "Companions", "items": [
        {"label": "Companions", "value": f"{len(companions['pets'])} of {unlocked} unlocked slots"
         if total else str(len(companions["pets"]))},
        {"label": "Eggs", "value": str(len(companions["eggs"]))},
        {"label": "Ready to hatch", "value": f"{hatchable} of {len(companions['eggs'])}"},
        {"label": "Can lay an egg", "value": str(can_lay)},
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
    out = [{"type": "text", "text": INTRO}, stats_section(companions, now)]
    if book.error:
        out.append({"type": "notice", "level": "info",
                    "text": f"Ability descriptions and harvest words are unavailable ({book.error})."})
    animals = discoveries.animal_by_seed()
    out.append(roster_table(companions, book, animals, ctx, now))
    if companions["eggs"]:
        out.append(eggs_table(companions, ctx, now))
    return out
