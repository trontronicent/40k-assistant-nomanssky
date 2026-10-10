"""Companions, their eggs and their creature-battle abilities - plugin 0.15.0 "Discovery".

What is *measured* (the real save and the installed game, build 25732212, 2026-10-10) and what is not:

* **The save** (``BaseContext.PlayerStateData``): ``Pets`` and ``Eggs`` are fixed-size arrays (30 and 18 entries in the
  measured save) whose unused entries are empty records - **11 pets and 4 eggs** really exist there, matching
  ``UnlockedPetSlots`` (30 booleans, 11 true). A pet carries ``CustomName`` (3 of 30 set), ``CreatureID`` (``^COW``),
  ``CreatureType.CreatureType`` (Prey / Predator ...), ``Biome.Biome``, ``Trust`` (0.75; an egg 0.70), ``BirthTime``,
  ``LastEggTime``, ``UA`` (the packed address it comes from), ``Traits`` (three signed floats), ``Moods`` (two
  floats), the genus/species/creature seeds, and the battle record ``PetBattlerVictories``,
  ``PetBattlerTreatsEaten`` (3), ``PetBattlerTreatsAvailable``, ``PetBattlerCoreStatClassOverrides`` (3 x S/A/B/C =
  Combat Effectiveness, Health, Agility) and ``PetBattlerMoves`` (5 template ids such as ``^ATTACK_DUST``).
* **The move table** ``petbattlermovestable.mbin`` (61 records of 312 bytes; the self-calibrating reader finds them):
  id at 0x10, the game's own English description at 0x34, the class (ATTACK, HEAL, MULTI, PURGE ...) at 0xB4. All
  five moves of a measured pet were found in it. It sits in ``NMSARC.Precache.pak`` - without the pak hint it
  opens 17 paks. A move's *displayed name* (``UI_PB_MOVE_<AFFINITY>_<KIND><n>``, "Landslide") depends on the
  creature's affinity, which the save does not hold, so abilities are shown by template and description.
* **Harvest**: ``UI_LABEL_HARVEST_<CreatureID>`` ("Collect Milk") and ``FOOD_<CreatureID>_VEG|MEAT_NAME_L``
  ("Fresh Milk", "Raw Steak") are language keys, so every companion's harvest is read, not guessed.
* **Not claimed**: what the three ``Traits`` floats mean (the community describes three helpful/playful,
  gentle/aggressive, devoted/independent pairs; the float count agrees, the order is unconfirmed), the egg cooldown
  (no constant in the game files), and the species name the game shows (generated from the seeds; no name table
  exists in the 84,330 English strings). They are shown raw and labelled as such.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import hgpak, mbin

MOVES_FILE = "metadata/simulation/gametables/petbattler/petbattlermovestable.mbin"
MOVES_PAK = "NMSARC.Precache.pak"
ID_AT, TEXT_AT, TEXT_BYTES, KIND_AT = 0x10, 0x34, 0x80, 0xB4
MAX_MOVE_RECORDS = 400
STAT_NAMES = ("Combat Effectiveness", "Health", "Agility")       # the order of PetBattlerCoreStatClassOverrides
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
        self.type_names: dict[str, str] = {}

    @classmethod
    def from_texts(cls, english: dict, local: dict | None, language: str | None) -> "PetBook":
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
    classes = raw.get("PetBattlerCoreStatClassOverrides")
    moves = raw.get("PetBattlerMoves")
    return {
        "name": raw.get("CustomName") if isinstance(raw.get("CustomName"), str) and raw["CustomName"].strip() else None,
        "id": creature_id(raw.get("CreatureID")),
        "type": inner("CreatureType", "CreatureType") or "",
        "biome": inner("Biome", "Biome") or "",
        "trust": round(_number(raw.get("Trust")), 3),
        "born": int(_number(raw.get("BirthTime"))) or None,
        "egg": int(_number(raw.get("LastEggTime"))) or None,
        "ua": _address(raw.get("UA")),
        "summoned": bool(raw.get("HasBeenSummoned")),
        "wins": int(_number(raw.get("PetBattlerVictories"))),
        "treats": [int(_number(v)) for v in eaten[:3]] if isinstance(eaten, list) else [],
        "treats_free": int(_number(raw.get("PetBattlerTreatsAvailable"))),
        "classes": [(c.get("InventoryClass") if isinstance(c, dict) else None) or "?" for c in classes[:3]]
        if isinstance(classes, list) else [],
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


def traits_text(pet: dict) -> str:
    """The three raw trait floats, signed - labelled raw because their meaning is not confirmed."""
    return " / ".join(f"{v:+.2f}" for v in pet["traits"]) if pet["traits"] else "–"


# The six personality words the game shows in a companion's Personality panel (UI_PET_*_RATING), in the order the
# game's own egg text lists them. The save holds only THREE floats; which words they stand for, in which order and with
# which sign is NOT confirmed, so the tooltip names the six and says so.
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


def trait_names(book: "PetBook") -> list[str]:
    """The six personality words, in the game's language where the game files were read, else the English fallback."""
    return [book.trait_names.get(k) or TRAIT_FALLBACK[k] for k in TRAIT_ORDER]


def type_note(creature_type: str, book: "PetBook") -> str:
    """One line for the Type tooltip: what the type means, or an honest 'not documented' for an unknown value."""
    key = (creature_type or "").upper()
    note = TYPE_NOTES.get(key)
    if note is None:
        return f"{creature_type or 'Unknown'}: the game files have no description of this type."
    word = book.type_names.get(key)
    return note.replace(f"{key.title()}:", f"{word}:", 1) if word else note


def stat_classes_text(pet: dict) -> str:
    """'Combat Effectiveness C, Health C, Agility C' (the order of the three overrides)."""
    return ", ".join(f"{n} {c}" for n, c in zip(STAT_NAMES, pet["classes"], strict=False)) if pet["classes"] else "–"


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

