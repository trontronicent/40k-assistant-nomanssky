"""Companions, their eggs and their creature-battle abilities - plugin 0.15.0 "Discovery".

What is *measured* (the real save and the installed game, build 25732212, 2026-10-10) and what is not:

* **The save** (``BaseContext.PlayerStateData``): ``Pets`` and ``Eggs`` are fixed-size arrays (30 and 18 entries in the
  measured save) whose unused entries are empty records - **11 pets and 4 eggs** really exist there, matching
  ``UnlockedPetSlots`` (30 booleans, 11 true). A pet carries ``CustomName`` (3 of 30 set), ``CreatureID`` (``^COW``),
  ``CreatureType.CreatureType`` (Prey / Predator ...), ``Biome.Biome``, ``Trust`` (0.75; an egg 0.70), ``BirthTime``,
  ``LastEggTime``, ``UA`` (the packed address it comes from), ``Traits`` (three signed floats), ``Moods`` (two
  floats), the genus/species/creature seeds, and the battle record ``PetBattlerVictories``,
  ``PetBattlerTreatsEaten`` (3), ``PetBattlerTreatsAvailable``, ``PetBattlerCoreStatClassOverrides`` (3 x S/A/B/C,
  **inert** - see below) and ``PetBattlerMoves`` (5 template ids such as ``^ATTACK_DUST``).
* **The three battle stats** (measured 2026-10-20 against the Companion UI over 11 companions; the readings and the
  reasoning are in ``research/pet_classes.json``). Two different quantities share the names *Combat Effectiveness /
  Agility / Health*, and only one of them is in the save:

  - The **number** the UI shows as ``x/10`` is exactly ``PetBattlerTreatsEaten``, whose order is ``(Health,
    Agility, Combat Effectiveness)`` - the reverse of the UI's. Confirmed on two pets, six values, no mismatch,
    the second predicted before it was read. A stat caps at 10 treats eaten.
  - The **tier letter** (C/B/A/S) is unchangeable, fixed at hatch, derived from the creature seed, and **not in
    the save**: ``PetBattlerCoreStatClassOverrides`` is ``[C, C, C]`` with ``PetBattlerUseCoreStatClassOverrides``
    false on every pet, brand-new ones included, while the UI shows C through S. That array is an override slot
    the game ignores and must never be shown as the tier. Nothing moves a letter - not treats (proven on a clone
    pair, and as a before/after on one pet taken to its cap), not gene editing, not a deliberate size edit. The
    derivation is engine code, not a game data table, so the letters cannot be shown here at all; only the treat
    numbers are. *Overall* is ``ceil(mean)`` of the three letters, so it carries nothing extra either.

    What a tier *does* comes from the player, not from a save (nothing here can measure it): it scales **how much
    benefit the category gets from each treat**. A rate of return, not a cap - every stat accepts the same 10
    treats whatever its tier, which is why Unzy shows a maxed 10/10 Health at tier C. So the treat numbers this
    module reports are **investment, not strength**, and two companions with equal treats need not be equally
    strong; nothing here may imply otherwise or rank companions by power.
* **The move table** ``petbattlermovestable.mbin`` (61 records of 312 bytes; the self-calibrating reader finds them):
  id at 0x10, the game's own English description at 0x34, the class (ATTACK, HEAL, MULTI, PURGE ...) at 0xB4. All
  five moves of a measured pet were found in it. It sits in ``NMSARC.Precache.pak`` - without the pak hint it
  opens 17 paks. A move's *displayed name* (``UI_PB_MOVE_<AFFINITY>_<KIND><n>``, "Landslide") depends on the
  creature's affinity, which the save does not hold, so abilities are shown by template and description.
* **Harvest**: ``UI_LABEL_HARVEST_<CreatureID>`` ("Collect Milk") and ``FOOD_<CreatureID>_VEG|MEAT_NAME_L``
  ("Fresh Milk", "Raw Steak") are language keys, so every companion's harvest is read, not guessed.
* **Traits** are three signed floats, one axis each, read against the player's own in-game values (3 pets, 8
  readings): [0] ``+`` Helpfulness / ``-`` Playfulness, [1] ``+`` Aggression / ``-`` Gentleness, [2] ``+`` Independence
  / ``-`` Devotion; the percentage the game shows is ``abs(value)``. Confirmed by the player: Playfulness (-0.23,
  -0.80), Helpfulness (+0.25), Gentleness (-0.73, -0.77, -0.38), Devotion (-0.16), Independence (+0.20).
  **Inferred only**: Aggression as the positive side of [1] (both Predators carry +0.77 / +0.79, every other pet is
  negative).
* **The egg timers** are measured and live under *the egg timers*, below: an egg is hatchable 24 h after it was laid
  (confirmed in the game) and a companion lays from 28 days old (measured on the save). Only the interval between
  two eggs is still a candidate rather than a reading.
* **Not claimed**: the species name the game shows (generated from the seeds; no name table exists in the 84,330
  English strings).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import hgpak, mbin

MOVES_FILE = "metadata/simulation/gametables/petbattler/petbattlermovestable.mbin"
MOVES_PAK = "NMSARC.Precache.pak"
ID_AT, TEXT_AT, TEXT_BYTES, KIND_AT = 0x10, 0x34, 0x80, 0xB4
MAX_MOVE_RECORDS = 400
TREAT_STATS = ("Health", "Agility", "Combat Effectiveness")       # the measured order of PetBattlerTreatsEaten
TREAT_UI_ORDER = (2, 1, 0)                                        # the Companion UI lists them the other way round
TREAT_CAP = 10                                                    # a stat stops accepting treats at 10
KG_PER_SCALE = 40.0                                               # measured: the game's weight is 40 x Scale
MAX_PETS, MAX_EGGS = 60, 60                                       # the app's slots are 30; a damaged save is cut
SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class Move:
    """One ability template of the battle table."""
    id: str
    kind: str
    text: str


def parse_moves(data: bytes) -> dict[str, Move]:
    """{template id: Move} from the move table; raises ``mbin.MbinError`` when it does not look like one."""
    start, count = mbin.root_list(data)
    if not 0 < count <= MAX_MOVE_RECORDS:
        raise mbin.MbinError(f"move table: implausible record count {count}")
    size = mbin.record_size(data, start, count)
    if size < KIND_AT + 0x10:
        raise mbin.MbinError(f"move table: implausible record size {size}")
    moves: dict[str, Move] = {}
    for i in range(count):
        base = start + i * size
        move_id = _text(data, base + ID_AT, 0x20)
        if move_id and re.fullmatch(r"[A-Z0-9_]{2,31}", move_id):
            moves[move_id] = Move(move_id, _text(data, base + KIND_AT, 0x20), _text(data, base + TEXT_AT, TEXT_BYTES))
    if not moves:
        raise mbin.MbinError("move table: no move ids found")
    return moves


def _text(data: bytes, at: int, size: int) -> str:
    """A zero-terminated ASCII field (latin-1 so a stray byte never raises)."""
    return data[at:at + size].split(b"\x00", 1)[0].decode("latin-1").strip()


def load_moves(install) -> dict[str, Move]:
    """The move table of the installed game (blocking); {} when there is no installation. The pak hint is the
    difference between one pak and seventeen."""
    if install is None:
        return {}
    with hgpak.PakSet(install.pcbanks, {MOVES_FILE: MOVES_PAK}) as paks:
        return parse_moves(paks.read(MOVES_FILE))


# ---- the game's words ------------------------------------------------------------------------------------

_HARVEST_RE = re.compile(r"^UI_LABEL_HARVEST_([A-Z0-9]+)$")
_FOOD_RE = re.compile(r"^FOOD_([A-Z0-9]+?)_(VEG|MEAT)_NAME_L$")
_AFFINITY_RE = re.compile(r"^UI_PB_AFFINITY_([A-Z]+)_L$")
_STAT_HEADER_RE = re.compile(r"^UI_PB_STAT_HEADER_(BUDGET|HEALTH|SPEED)$")
_TRAIT_RE = re.compile(r"^UI_PET_(HELPFUL|PLAYFUL|GENTLENESS|AGGRESSION|INDEPENDENCE|ATTACHMENT)_RATING$")
_TYPE_RE = re.compile(r"^(PASSIVE|PREY|PREDATOR)1$")


def wanted_key(key: str) -> bool:
    """The language keys the companions need (harvest, food, affinity and stat words)."""
    return bool(_HARVEST_RE.match(key) or _FOOD_RE.match(key) or _AFFINITY_RE.match(key) or _STAT_HEADER_RE.match(key)
                or _TRAIT_RE.match(key) or _TYPE_RE.match(key))


def _both(english: str | None, local: str | None) -> str | None:
    """'English (local)' when the game language differs, else the English text."""
    english = " ".join((mbin.clean_text(english) or "").split())
    local = " ".join((mbin.clean_text(local) or "").split())
    if not english:
        return local or None
    return f"{english} ({local})" if local and local.casefold() != english.casefold() else english


class PetBook:
    """The game's words for companions plus the move table; empty with ``error`` when they could not be read."""

    def __init__(self, error: str | None = None):
        self.error = error
        self.moves: dict[str, Move] = {}
        self._harvest: dict[str, str] = {}
        self._food: dict[str, dict[str, str]] = {}
        self.affinities: dict[str, str] = {}
        self.trait_names: dict[str, str] = {}
        self.trait_short: dict[str, str] = {}
        self.type_names: dict[str, str] = {}

    @classmethod
    def from_texts(cls, english: dict, local: dict | None, language: str | None) -> PetBook:
        """Build from the language texts (``local`` = the game language, None when it is English)."""
        book = cls()
        local = local or {}
        for key, text in english.items():
            if m := _HARVEST_RE.match(key):
                book._harvest[m.group(1)] = _both(text, local.get(key)) or ""
            elif m := _FOOD_RE.match(key):
                book._food.setdefault(m.group(1), {})[m.group(2).lower()] = _both(text, local.get(key)) or ""
            elif m := _AFFINITY_RE.match(key):
                book.affinities[m.group(1)] = _both(text, local.get(key)) or ""
            elif m := _TRAIT_RE.match(key):
                book.trait_names[m.group(1)] = _both(text, local.get(key)) or ""
                book.trait_short[m.group(1)] = " ".join((mbin.clean_text(local.get(key) or text) or "").split())
            elif m := _TYPE_RE.match(key):
                book.type_names[m.group(1)] = _both(text, local.get(key)) or ""
        return book

    def harvest(self, creature: str) -> dict:
        """{"action": "Collect Milk", "veg": "Fresh Milk", "meat": "Raw Steak"} - only the parts the game has."""
        out = {}
        if self._harvest.get(creature):
            out["action"] = self._harvest[creature]
        out.update({k: v for k, v in self._food.get(creature, {}).items() if v})
        return out

    def move(self, template: str) -> Move | None:
        return self.moves.get(template)


# ---- the save ---------------------------------------------------------------------------------------------

def creature_id(raw) -> str:
    """'^COW' -> 'COW'; anything unusable -> ''."""
    text = raw if isinstance(raw, str) else ""
    return text.lstrip("^").strip().upper() if re.fullmatch(r"\^?[A-Za-z0-9_]{1,40}", text) else ""


def _number(value, default=0.0) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _seed(value) -> int | None:
    """A seed field: ``[true, "0x…"]``, ``"0x…"`` or an int."""
    if isinstance(value, list) and len(value) == 2:
        value = value[1]
    if isinstance(value, str):
        try:
            return int(value, 16)
        except ValueError:
            return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _address(value) -> int | None:
    if isinstance(value, str):
        try:
            return int(value, 16)
        except ValueError:
            return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def compact(raw: dict) -> dict:
    """The fields of one pet or egg the plugin uses, JSON-safe and bounded (what the snapshot keeps)."""
    def inner(name, key):
        return (raw.get(name) or {}).get(key) if isinstance(raw.get(name), dict) else None

    eaten = raw.get("PetBattlerTreatsEaten")
    moves = raw.get("PetBattlerMoves")
    return {
        "name": raw.get("CustomName") if isinstance(raw.get("CustomName"), str) and raw["CustomName"].strip() else None,
        "id": creature_id(raw.get("CreatureID")),
        "type": inner("CreatureType", "CreatureType") or "",
        "biome": inner("Biome", "Biome") or "",
        "trust": round(_number(raw.get("Trust")), 3),
        "scale": round(_number(raw.get("Scale")), 6),
        "born": int(_number(raw.get("BirthTime"))) or None,
        "egg": int(_number(raw.get("LastEggTime"))) or None,
        "ua": _address(raw.get("UA")),
        "summoned": bool(raw.get("HasBeenSummoned")),
        "wins": int(_number(raw.get("PetBattlerVictories"))),
        "treats": [int(_number(v)) for v in eaten[:3]] if isinstance(eaten, list) else [],
        "treats_free": int(_number(raw.get("PetBattlerTreatsAvailable"))),
        "moves": [m.lstrip("^") for m in moves[:5] if isinstance(m, str) and m.strip("^")] if isinstance(moves, list) else [],
        "traits": [round(_number(v), 3) for v in raw["Traits"][:3]] if isinstance(raw.get("Traits"), list) else [],
        "moods": [round(_number(v), 3) for v in raw["Moods"][:2]] if isinstance(raw.get("Moods"), list) else [],
        "seeds": [_seed(raw.get(k)) for k in ("CreatureSeed", "CreatureSecondarySeed", "SpeciesSeed", "GenusSeed")],
    }


def compact_all(player_state: dict) -> dict:
    """{"pets": [...], "eggs": [...], "slots": [unlocked, total]} from ``PlayerStateData`` (bounded).

    ``Pets`` and ``Eggs`` are fixed-size arrays: the real save holds 30 and 18 entries but only 11 pets and 4 eggs
    exist (11 unlocked slots), the rest are empty records (blank ``CreatureID``, trust 0). Those are dropped.
    """
    pets = [c for p in (player_state.get("Pets") or [])[:MAX_PETS] if isinstance(p, dict) and (c := compact(p))["id"]]
    eggs = [c for e in (player_state.get("Eggs") or [])[:MAX_EGGS] if isinstance(e, dict) and (c := compact(e))["id"]]
    slots = player_state.get("UnlockedPetSlots")
    slots = [sum(1 for s in slots if s is True), len(slots)] if isinstance(slots, list) else [0, 0]
    return {"pets": pets, "eggs": eggs, "slots": slots}


def display_name(pet: dict) -> str:
    """The pet's name, or 'Cow (unnamed)' - the genus token is the only name the save gives it."""
    return pet["name"] or f"{pet['id'].title() or 'Creature'} (unnamed)"


def age_days(pet: dict, now: float) -> int | None:
    """Whole days since it was born or hatched, or None when the save has no birth time."""
    return max(0, int((now - pet["born"]) // SECONDS_PER_DAY)) if pet.get("born") else None


def trust_text(pet: dict) -> str:
    return f"{round(pet['trust'] * 100)} %"


# ---- the egg timers -------------------------------------------------------------------------------------
#
# Measured on the real save (2026-10-21, build 25732212); this module's old "the egg cooldown is not in the game
# files" was wrong - ``gccreatureglobals.mbin`` sits in ``NMSARC.globals.pak`` and holds durations as int32 (four
# 86,400 and one 1,209,600). An mbin carries no field names, so each constant below says how it was pinned.
#
# What the save holds, read by pairing every egg with its parent:
# * an **egg**'s ``BirthTime`` is the moment it was laid and its ``LastEggTime`` is its *parent's* ``BirthTime``
#   (so an egg names its parent); confirmed on all four egg/pet pairs in the save.
# * a **pet**'s ``LastEggTime`` is the moment it last produced an egg - the pet's field and its egg's ``BirthTime``
#   are 2-12 s apart on all four pairs.
HATCH_SECONDS = 86_400              # confirmed in the game: an egg reads "ready to hatch in X" for 24 h after laying
LAY_MIN_AGE = 28 * SECONDS_PER_DAY  # measured: every pet under 28 days has LastEggTime == BirthTime, every older one
                                    # that never laid has it stamped at exactly BirthTime + 28 d (14 pets). One had
                                    # crossed 28 days three hours before the save and was stamped at birth + 28 d,
                                    # not at "now", so the game computes the gate from BirthTime.
LAY_COOLDOWN = 14 * SECONDS_PER_DAY  # NOT confirmed: the only other duration in creature globals (1,209,600 s). The
                                     # game's own extra conditions are shown beside it, so this cannot read as fact.
# The game's words for what else blocks laying (UI_PET_EGG_COST_*) - none of which a save can see.
LAY_BLOCKERS = ("Feeling hungry", "Feeling sad", "Not in native climate", "Requires additional nutrition")


def duration_text(seconds: float) -> str:
    """'6 d 4 h', '23 h 50 min', '12 min' - the two biggest units that are not zero."""
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, SECONDS_PER_DAY)
    hours, minutes = divmod(rest // 60, 60)
    if days:
        return f"{days} d {hours} h" if hours else f"{days} d"
    if hours:
        return f"{hours} h {minutes} min" if minutes else f"{hours} h"
    return f"{minutes} min"


def hatch_at(egg: dict) -> int | None:
    """When this egg becomes hatchable (laid + 24 h), or None when the save has no laying time."""
    return egg["born"] + HATCH_SECONDS if egg.get("born") else None


def hatch_text(egg: dict, now: float) -> str:
    """'Ready to hatch' or 'in 5 h 20 min'; '–' when the save holds no laying time."""
    ready = hatch_at(egg)
    if ready is None:
        return "–"
    return "Ready to hatch" if now >= ready else f"in {duration_text(ready - now)}"


def parent_of(egg: dict, roster: list[dict]) -> dict | None:
    """The companion this egg came from: its ``LastEggTime`` is that pet's ``BirthTime``, same creature."""
    return next((p for p in roster if p.get("born") and p["born"] == egg.get("egg") and p["id"] == egg["id"]), None)


def lay_at(pet: dict) -> int | None:
    """The earliest moment this pet can produce an egg again, or None without the save's times.

    Two gates: a companion lays from ``LAY_MIN_AGE`` after its birth, and again ``LAY_COOLDOWN`` after its last egg.
    """
    if not (pet.get("born") and pet.get("egg")):
        return None
    return max(pet["born"] + LAY_MIN_AGE, pet["egg"] + LAY_COOLDOWN)


def lay_text(pet: dict, now: float, has_egg: bool = False) -> str:
    """'Ready', 'Egg waiting', 'Too young (in 6 d 4 h)' or 'in 3 d 2 h' - the egg side of one companion."""
    ready = lay_at(pet)
    if ready is None:
        return "–"
    if has_egg:
        return "Egg waiting"
    if now < pet["born"] + LAY_MIN_AGE:
        return f"Too young (in {duration_text(pet['born'] + LAY_MIN_AGE - now)})"
    return "Ready" if now >= ready else f"in {duration_text(ready - now)}"


def traits_text(pet: dict) -> str:
    """The three raw trait floats, signed - labelled raw because their meaning is not confirmed."""
    return " / ".join(f"{v:+.2f}" for v in pet["traits"]) if pet["traits"] else "–"


# The six personality words the game shows in a companion's Personality panel (UI_PET_*_RATING), in the order the
# game's own egg text lists them. The save holds only THREE floats; which words they stand for, in which order and with
# which sign is NOT confirmed, so the tooltip names the six and says so.
# (positive side, negative side) of the three stored values - see the module docstring for how this was read.
TRAIT_AXES = (("HELPFUL", "PLAYFUL"), ("AGGRESSION", "GENTLENESS"), ("INDEPENDENCE", "ATTACHMENT"))
TRAIT_ORDER = ("HELPFUL", "PLAYFUL", "GENTLENESS", "AGGRESSION", "INDEPENDENCE", "ATTACHMENT")
TRAIT_FALLBACK = {"HELPFUL": "Helpfulness", "PLAYFUL": "Playfulness", "GENTLENESS": "Gentleness",
                  "AGGRESSION": "Aggression", "INDEPENDENCE": "Independence", "ATTACHMENT": "Devotion"}

# What the game's own text says about the creature types. The three words are the game's labels; the behaviour
# sentences paraphrase the game's companion help ("Bait ... will calm predators or other angry creatures",
# "Feeding a creature gains their trust"). The game has no definition text for a type.
TYPE_NOTES = {
    "PASSIVE": "Passive: peaceful, does not attack. Can be fed, tamed and adopted straight away.",
    "PREY": "Prey: skittish; flees when approached. Feed it to gain its trust.",
    "PREDATOR": "Predator: hunts and attacks. Bait calms it, after which it can be fed and adopted.",
}


def personality(pet: dict) -> list[tuple[str, int]]:
    """[(trait key, percent)] for the three axes: the side the sign points to, and abs(value) as a percentage."""
    return [(axis[0] if v >= 0 else axis[1], round(abs(v) * 100)) for axis, v in zip(TRAIT_AXES, pet["traits"], strict=False)]


def personality_text(pet: dict, book: PetBook) -> str:
    """'Playfulness 23% / Gentleness 77% / Devotion 16%' in the game's language (English when it was not read)."""
    if not pet["traits"]:
        return "–"
    return " / ".join(f"{book.trait_short.get(k) or TRAIT_FALLBACK[k]} {p}%" for k, p in personality(pet))


def trait_names(book: PetBook) -> list[str]:
    """The six personality words, in the game's language where the game files were read, else the English fallback."""
    return [book.trait_names.get(k) or TRAIT_FALLBACK[k] for k in TRAIT_ORDER]


def type_note(creature_type: str, book: PetBook) -> str:
    """One line for the Type tooltip: what the type means, or an honest 'not documented' for an unknown value."""
    key = (creature_type or "").upper()
    note = TYPE_NOTES.get(key)
    if note is None:
        return f"{creature_type or 'Unknown'}: the game files have no description of this type."
    word = book.type_names.get(key)
    return note.replace(f"{key.title()}:", f"{word}:", 1) if word else note


def treats_text(pet: dict) -> str:
    """'Combat Effectiveness 6/10, Agility 0/10, Health 4/10' - the treats invested in each battle stat.

    Named and ordered as the game's Companion UI shows them, which is the reverse of how the save stores them
    (``TREAT_STATS``). This is the stat *number*, not its class letter: the letters are not in the save at all.
    """
    eaten = pet["treats"]
    return ", ".join(f"{TREAT_STATS[i]} {eaten[i]}/{TREAT_CAP}"
                     for i in TREAT_UI_ORDER if i < len(eaten)) if eaten else "–"


def size_text(pet: dict) -> str:
    """'3.7 m' - the size the game displays, which is ``Scale`` rounded to one decimal; '–' without a scale."""
    return f"{pet['scale']:.1f} m" if pet.get("scale") else "–"


def weight_text(pet: dict) -> str:
    """'147.3 kg' - the weight the game displays, measured to be ``KG_PER_SCALE * Scale``; '–' without a scale."""
    return f"{KG_PER_SCALE * pet['scale']:.1f} kg" if pet.get("scale") else "–"


def move_lines(pet: dict, book: PetBook) -> list[str]:
    """One line per ability: 'ATTACK_DUST (ATTACK): Deals direct damage of specific affinity'."""
    out = []
    for template in pet["moves"]:
        move = book.move(template)
        out.append(f"{template} ({move.kind}): {move.text}" if move and move.text else
                   f"{template}{' (' + move.kind + ')' if move and move.kind else ''}")
    return out


def first_scan(pet: dict, animals: dict[int, dict]) -> dict | None:
    """The animal discovery record of this pet's species creature (join by creature seed), or None."""
    seed = pet["seeds"][0] if pet.get("seeds") else None
    return animals.get(seed) if seed is not None else None


def pack_seed(seed: int | None) -> str:
    """A seed as shown in tooltips (hex), or '–'."""
    return f"0x{seed:016X}" if isinstance(seed, int) else "–"

