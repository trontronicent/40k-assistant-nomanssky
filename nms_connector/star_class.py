"""Star classes - what the game calls a system's *spectral class* - and the worlds they make (pure).

The game shows the class on the galaxy map's analysis panel: ``GLXY_SPECTRAL`` = "SPECTRAL",
``GLXY_ANALYSIS_SPECTRAL`` = "Class %PROCSPEC%". The string itself ("G2f", "K3p") is built in the game at
display time; nothing in the save or in the galaxy map's star record holds it. What *is* stored is the star
**type** (``GcGalaxyStarAttributesData.Type``, read by ``memory.parse_star_attributes`` and predicted by
``procgen``): one of the five colours. So this module gives the class **letters** of a colour, not the digit
and the suffix - those are flavour the game rolls per system, and no source confirms an effect in play.

* ``CLASSES``: per colour the Harvard class letters, the hyperdrive upgrade that reaches it (the game's own
  item descriptions name the colour: Cadmium Drive -> red, Emeril -> green, Indium -> blue, Atlantid ->
  purple) and one line about the systems.
* ``weights``: the game's own biome weights per star type, decoded from
  ``metadata/simulation/solarsystem/biomes/biomelistperstartype.mbin`` into ``research/star_classes.json``
  (see that file for the layout and the cross-check against a real save). Yellow stars have their own rows
  for lush and empty galaxies.
* ``star_cell`` / ``planet_type_cell``: the two tooltips the page shows - on a system's star and on a
  planet's type.

**The limits of the weight table, measured on a 2,673-planet save (2026-10-21).** What it predicts and the
save agree on everything colour-specific: the red, green and blue exotic sub-biomes occur only at a star of
that colour, swamp and lava worlds only as prime planets, lush worlds are twice as common at yellow stars.
Two slots do *not* agree: ``Dead`` carries weight 2 at every colour, yet not one of the 2,673 planets is a
dead world, and ``Exotic`` is 0 for yellow stars in a normal galaxy, yet 10% of the planets at yellow stars
are exotic. The generator evidently decides those two elsewhere (gas giants and water worlds are missing
from the table altogether), so the tooltip never promises a dead or exotic world from this table.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import galaxies, logs

RESEARCH_FILE = Path(__file__).resolve().parent.parent / "research" / "star_classes.json"

#: Biome slots the weight table gets wrong (see the module docstring): never named in a tooltip.
UNTRUSTED_BIOMES = ("Dead", "Exotic")

#: How many world types a tooltip names at most - the tooltip stays a tooltip.
MAX_WORLDS = 4


@dataclass(frozen=True)
class StarClass:
    """One star colour: how the game classes it, what reaches it, what it means."""
    colour: str
    letters: str                   # Harvard class letters the game uses for this colour
    drive: str | None              # the hyperdrive upgrade a ship needs, None for yellow
    note: str


#: The five star types, in the order the game stores them (``memory.STAR_TYPES``). The letters are the
#: community's reading of the class strings the game shows (No Man's Sky wiki / NMS Discoveries wiki, read
#: 2026-10-21); the game files hold the colour, never the letter, so they are named as what the class
#: *starts with* and nothing is claimed about the digit or the suffix.
CLASSES = {
    "Yellow": StarClass("Yellow", "F or G", None,
                        "Reachable with the standard hyperdrive; the systems you start among."),
    "Green": StarClass("Green", "E", "Emeril Drive",
                       "Green exotic worlds occur only here, and swamp worlds are twice as likely."),
    "Blue": StarClass("Blue", "O or B", "Indium Drive",
                      "Blue exotic worlds occur only here."),
    "Red": StarClass("Red", "K or M", "Cadmium Drive",
                     "Red exotic worlds occur only here, and lava worlds are twice as likely."),
    "Purple": StarClass("Purple", "X or Y", "Atlantid Drive",
                        "Dissonant space: the only star type whose world list includes water worlds."),
}

#: The digit and the suffix of a class string, for the tooltip's last line.
SUFFIX_NOTE = ("The game adds a digit and sometimes a letter (G2f, K3p). Both are borrowed from real "
               "astronomy, are rolled per system, and no source confirms an effect in play.")


def load_research(path: Path | None = None) -> dict:
    """The decoded weight table ({} when the file is missing, as with the other research files)."""
    data = logs.read_json(path or RESEARCH_FILE, "The researched star class file")
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def research() -> dict:
    """`load_research`, read once per process: the view is built on every 5 s poll and this is a shipped
    file that cannot change under a running host."""
    return load_research()


def row_name(colour: str, galaxy_index=None) -> str:
    """The weight row for a star: yellow stars generate differently in lush and in empty galaxies."""
    if colour != "Yellow" or galaxy_index is None:
        return colour
    kind = galaxies.kind(galaxy_index)
    return f"Yellow ({kind} galaxy)" if kind in (galaxies.LUSH, galaxies.EMPTY) else colour


def weights(colour: str, galaxy_index=None, prime: bool = False, data: dict | None = None) -> dict[str, float]:
    """The game's biome weights for this star ({} when the research file is missing or the colour unknown)."""
    rows = (data if data is not None else research()).get("weights") or {}
    row = rows.get(row_name(colour, galaxy_index)) or rows.get(colour) or {}
    return {b: w for b, w in (row.get("prime" if prime else "normal") or {}).items() if isinstance(w, (int, float))}


def favoured(colour: str, galaxy_index=None, data: dict | None = None) -> list[str]:
    """The world types this star makes more likely than the common ones, heaviest first.

    Only weights above 1 count: every star type carries the six ordinary biomes at weight 1, so listing
    them would say nothing. ``UNTRUSTED_BIOMES`` are left out (see the module docstring)."""
    out: list[tuple[float, str]] = []
    for prime in (False, True):
        for biome, weight in weights(colour, galaxy_index, prime, data).items():
            if weight > 1 and biome not in UNTRUSTED_BIOMES:
                out.append((weight, f"{biome} (as a prime planet)" if prime else biome))
    out.sort(key=lambda e: -e[0])
    seen, names = set(), []
    for _weight, name in out:
        base = name.split(" (")[0]
        if base not in seen:
            seen.add(base)
            names.append(name)
    return names[:MAX_WORLDS]


def stars_for(biome: str | None, data: dict | None = None) -> list[tuple[str, bool]]:
    """The star colours this world type is tied to, heaviest first, each with "more likely than average" -
    the other direction of the table, for a planet's tooltip.

    A type every colour generates is reduced to the colours that favour it (and is empty when none does):
    the six ordinary biomes occur at every star, so naming all five colours for them would say nothing."""
    if not biome or biome in UNTRUSTED_BIOMES:
        return []
    found: list[tuple[float, str]] = []
    for colour in CLASSES:
        best = max((weights(colour, None, prime, data).get(biome, 0.0) for prime in (False, True)), default=0.0)
        if best > 0:
            found.append((best, colour))
    if len(found) >= len(CLASSES):
        found = [e for e in found if e[0] > 1]
    found.sort(key=lambda e: (-e[0], e[1]))
    return [(colour, weight > 1) for weight, colour in found]


def class_text(colour: str | None) -> str | None:
    """'Yellow (class F or G)' - the star as the page names it, or None for a star not read yet."""
    entry = CLASSES.get(colour or "")
    return f"{colour} (class {entry.letters})" if entry else (colour or None)


def star_hint(colour: str | None, galaxy_index=None, source: str | None = None) -> str | None:
    """Tooltip of a system's star: what the class means, what reaches it, the worlds it favours."""
    entry = CLASSES.get(colour or "")
    if entry is None:
        return None
    blocks = [f"Spectral class {entry.letters}: what the galaxy map's analysis panel calls a {colour.lower()} "
              f"star. {entry.note}"]
    blocks.append(f"Reached with: {entry.drive}." if entry.drive
                  else "Reached with: the standard hyperdrive, no upgrade needed.")
    worlds = favoured(colour or "", galaxy_index)
    if worlds:
        blocks.append("More likely here than elsewhere:\n" + "\n".join(f"• {w}" for w in worlds)
                      + "\nFrom the game's own biome weights per star type.")
    if source:
        blocks.append(f"Source: {source}.")
    blocks.append(SUFFIX_NOTE)
    return "\n\n".join(blocks)


def star_cell(colour: str | None, galaxy_index=None, source: str | None = None):
    """A table cell / details value for a star: its colour and class, with the tooltip."""
    text = class_text(colour)
    if not text:
        return None
    hint = star_hint(colour, galaxy_index, source)
    return {"text": text, "hint": hint} if hint else text


def planet_class_lines(planet: dict, world_summary: str | None = None) -> list[str]:
    """The blocks of a planet's type tooltip: what the game's own type word means, then the world type."""
    biome, size = planet.get("biome"), planet.get("size")
    lines = ["Planetary class: the game's own words for this world - the type name the analysis visor shows, "
             "with 'Planet', 'Moon' or 'Planetoid' for its size class."]
    known = [v for v in (f"world type: {biome}" if biome else None, f"size class: {size}" if size else None) if v]
    if known:
        lines.append("Recorded " + ", ".join(known) + ".")
    if world_summary:
        lines.append(f"Such worlds: {world_summary}.")
    stars = stars_for(biome)
    if stars:
        named = [f"{class_text(colour)}{' - more likely' if more else ''}" for colour, more in stars]
        lines.append("Occurs at these star classes:\n" + "\n".join(f"• {n}" for n in named)
                     + "\nFrom the game's own biome weights per star type.")
    return lines


def planet_type_cell(text: str | None, planet: dict, world_summary: str | None = None):
    """A planet's Type cell: the game's description, with the planetary-class tooltip."""
    if not text:
        return None
    return {"text": text, "hint": "\n\n".join(planet_class_lines(planet, world_summary))}


def world_summaries(world_types) -> dict[str, str]:
    """{planet-record biome: the one-line summary of its world type} - ``worlds.WORLD_TYPES`` indexed the way
    a planet record names its biome."""
    out = {}
    for wt in world_types:
        for biome in wt.biomes:
            if wt.summary:
                out.setdefault(biome, wt.summary)
    return out
