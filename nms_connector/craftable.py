"""How often an item can be made from what the player holds, and the portal address as glyph names.

Chat test 2026-10-09: "how many of those can I make?" after "recipe for Antimatter" was answered "the data does not
contain the quantities of Chromatic Metal or Condensed Carbon" - the plugin knows the recipe and the holdings, the
model was left to do the sum (and "Hab ich genug Antimaterie für 3 Warpzellen?" had no ingredient totals at all).
Pure functions; the recipes and holdings are passed in."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

MAKE_WORDS = {"make", "craft", "build", "produce", "create", "refine", "cook", "herstellen", "herstellen", "bauen",
              "machen", "craften", "erzeugen", "raffinieren", "kochen", "fabricar", "hacer", "fabriquer", "faire",
              "fare", "stelle", "baue", "mache", "crafte"}
AMOUNT_WORDS = {"many", "much", "enough", "sufficient", "viele", "genug", "ausreichend", "wieviele", "wieviel",
                "cuántos", "cuantos", "combien", "quanti", "suffisamment", "suficiente"}
ENOUGH_WORDS = {"enough", "genug", "sufficient", "ausreichend", "suficiente", "suffisamment"}
GLYPH_WORDS = {"glyph", "glyphs", "glyphe", "glyphen", "glyphes", "glifos", "glifi"}
# The portal's 16 glyphs in the order of the address digits 0-F (the community's English names).
GLYPHS = ("Sunset", "Bird", "Face", "Diplo", "Eclipse", "Balloon", "Boat", "Bug", "Dragonfly", "Galaxy", "Voxel",
          "Fish", "Tent", "Rocket", "Tree", "Atlas")
NUMBER_RE = re.compile(r"\b(\d{1,4})\b")
FOLLOW_UP_RE = re.compile(r"\(follow-up to the user's")


def asks_craft_count(words: set[str]) -> bool:
    """True for "how many can I make", "do I have enough X for 3 ..." (a make word with an amount word, or enough)."""
    return bool(words & ENOUGH_WORDS) or bool(words & MAKE_WORDS and words & AMOUNT_WORDS)


def requested_times(question: str) -> int | None:
    """The number of items the player wants ("enough Antimatter for 3 Warp Cells" -> 3), from the message itself."""
    own = FOLLOW_UP_RE.split(question or "", maxsplit=1)[0]
    found = [int(n) for n in NUMBER_RE.findall(own) if 0 < int(n) <= 9999]
    return found[0] if found else None


def target_item(question: str, names: dict[str, list[str]]) -> str | None:
    """The item the wanted number belongs to: the first of `names` (item id -> its names) that follows the number in
    the message ("Antimatter for 3 Warp Cells" -> the Warp Cell, not the Antimatter). The 'enough for 3' check on the
    Antimatter too made the model read 'three can be made, so yes'. None without a number or an item after it."""
    own = FOLLOW_UP_RE.split(question or "", maxsplit=1)[0].lower()
    number = NUMBER_RE.search(own)
    best: tuple[int, str] | None = None
    for item, item_names in names.items():
        found = [own.find(n.lower()) for n in item_names if n and own.find(n.lower()) >= (number.end() if number else 0)]
        if number and found and (best is None or min(found) < best[0]):
            best = (min(found), item)
    return best[1] if best else None


def max_crafts(needs: Iterable[tuple[str, int]], have: dict[str, int]) -> tuple[int, str | None]:
    """(how often the recipe can be done, the ingredient that limits it); a recipe without ingredients: (0, None)."""
    best, limit = None, None
    for item, amount in needs:
        times = have.get(item, 0) // max(1, amount)
        if best is None or times < best:
            best, limit = times, item
    return (best or 0), limit


def option_line(needs: list[tuple[str, int]], have: dict[str, int], label_of: Callable[[str], str],
                times: int | None, output: int = 1) -> str:
    """"25 Chromatic Metal (you have 1,314) + 20 Condensed Carbon (you have 80): 4 times, limited by Condensed
    Carbon"; with a wanted number, also whether it is enough and what is missing."""
    parts = " + ".join(f"{a} {label_of(i)} (you have {have.get(i, 0):,})" for i, a in needs)
    count, limit = max_crafts(needs, have)
    line = f"{parts}: can be done {count:,} times" + (f" ({count * output:,} items)" if output != 1 else "")
    if limit and count < 1_000_000 and any(have.get(i, 0) // max(1, a) == count for i, a in needs) and len(needs) > 1:
        line += f", limited by {label_of(limit)}"
    if times:
        missing = [(i, a * times - have.get(i, 0)) for i, a in needs if have.get(i, 0) < a * times]
        line += (f"; enough for {times}" if not missing else
                 f"; NOT enough for {times}, missing " + ", ".join(f"{m:,} {label_of(i)}" for i, m in missing))
    return line


def glyph_names(portal: str | None) -> list[str]:
    """["Bird", "Sunset", ...] for a portal address of hex digits (any other character stops the reading)."""
    names = []
    for digit in (portal or "").strip():
        if digit.upper() not in "0123456789ABCDEF":
            return []
        names.append(GLYPHS[int(digit, 16)])
    return names
