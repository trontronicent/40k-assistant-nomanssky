"""The sixteen portal glyphs as our own vector artwork.

The game shows a portal address as twelve symbols; the save holds it as twelve hex digits. This module is the
single source of truth for what those symbols look like here: each glyph is a tuple of subpath strings in a
0..100 box, using only M, L, C and Z, drawn as strokes with no fills.

The artwork is this project's own, drawn after the game's symbols - the ready-made glyph files on fan sites are
Hello Games' art and are neither shipped nor downloaded. Stroke-only means the page can colour them with
``currentColor`` and the overlay can draw them in one colour.

Two emitters read this table: ``glyph_svg`` for the browser and ``glyph_png`` (glyph_raster.py) for Tk, which
cannot display SVG. ``GLYPH_ART_VERSION`` is part of every generated file name, so editing a shape invalidates
the generated assets with no cache-busting logic.
"""
from __future__ import annotations

GLYPH_ART_VERSION = 1
STROKE_WIDTH = 6.0

#: Glyph index -> its subpaths, in a 0..100 box. The index is the value of the address digit, so this lines up
#: with ``craftable.GLYPHS`` (0 Sunset ... F Atlas) and there is no second ordering to keep in step.
#: Drawn after the game's symbols; simplified to read at 20 px, which is the size the page and the overlay use.
GLYPHS: tuple[tuple[str, ...], ...] = (
    # 0 Sunset - a dome over three waves.
    ("M 14 56 C 14 28 86 28 86 56",
     "M 16 64 C 27 56 33 72 44 64 C 55 56 61 72 72 64 C 78 60 81 61 84 64",
     "M 20 78 C 31 70 37 86 48 78 C 57 72 63 80 70 78"),
    # 1 Bird - a swept wing over a tapering body.
    ("M 10 38 C 34 26 62 28 88 44 C 70 52 48 54 28 48",
     "M 16 56 C 38 50 60 52 82 60 C 62 70 36 70 18 62 Z",
     "M 18 62 C 26 70 38 74 48 74"),
    # 2 Face - a vertical bar with two crossbars and two eyes.
    ("M 50 16 L 50 84",
     "M 26 28 L 74 28",
     "M 30 52 L 70 52",
     "M 24 74 C 36 84 64 84 76 74",
     "M 30 40 L 32 40",
     "M 68 40 L 70 40"),
    # 3 Diplo - a long neck over a body with three legs.
    ("M 34 84 C 28 58 32 32 48 22 C 62 14 76 22 76 34 C 76 44 68 48 62 44",
     "M 34 84 C 46 86 62 84 74 76",
     "M 44 84 L 48 68",
     "M 56 82 L 60 66"),
    # 4 Eclipse - a filled-looking crescent beside an open circle.
    ("M 52 16 C 30 22 18 38 18 52 C 18 70 32 84 52 86 C 36 76 30 64 30 50 C 30 36 38 24 52 16 Z",
     "M 58 18 C 76 24 86 38 86 52 C 86 68 76 80 58 86",
     "M 56 52 L 86 52"),
    # 5 Balloon - a teardrop with a seam.
    ("M 50 14 C 70 34 76 54 50 88 C 24 54 30 34 50 14 Z",
     "M 50 20 L 50 82"),
    # 6 Boat - a hull with a mast and two yards.
    ("M 16 62 C 34 76 66 76 84 62 Z",
     "M 50 16 L 50 62",
     "M 50 28 L 70 36",
     "M 50 42 L 66 48",
     "M 50 14 L 50 18"),
    # 7 Bug - two horns over a segmented body.
    ("M 24 16 C 18 32 24 44 36 48",
     "M 76 16 C 82 32 76 44 64 48",
     "M 50 44 L 50 72",
     "M 32 56 L 68 56",
     "M 28 84 C 36 72 64 72 72 84"),
    # 8 Dragonfly - wings across a long tail.
    ("M 50 18 L 50 86",
     "M 50 36 C 32 30 20 36 14 48 C 28 54 42 50 50 44",
     "M 50 36 C 68 30 80 36 86 48 C 72 54 58 50 50 44",
     "M 38 58 L 62 58",
     "M 42 70 L 58 70"),
    # 9 Galaxy - two spiral arms around a core.
    ("M 50 50 C 50 28 34 18 22 26 C 12 32 14 48 28 54 C 44 62 62 56 68 42",
     "M 50 50 C 50 72 66 82 78 74 C 88 68 86 52 72 46 C 56 38 38 44 32 58"),
    # A Voxel - a hexagon with a dot.
    ("M 50 14 L 84 33 L 84 67 L 50 86 L 16 67 L 16 33 Z",
     "M 49 34 L 51 34"),
    # B Fish - a body with a tail and a fin.
    ("M 18 54 C 34 38 62 36 76 48 C 80 51 84 52 88 52 C 84 58 80 60 76 60 C 62 70 34 68 18 54 Z",
     "M 46 40 L 52 30 L 58 42",
     "M 30 52 L 36 52"),
    # C Tent - a peak with a doorway and a ground line.
    ("M 50 16 C 40 38 32 62 24 84",
     "M 50 16 C 60 38 68 62 76 84",
     "M 16 84 L 84 84",
     "M 42 84 C 44 70 56 70 58 84"),
    # D Rocket - a nose, a body and two fins.
    ("M 50 14 C 60 28 64 46 64 62 L 36 62 C 36 46 40 28 50 14 Z",
     "M 36 62 L 24 84 L 38 76",
     "M 64 62 L 76 84 L 62 76",
     "M 44 80 L 56 80"),
    # E Tree - a trunk that forks twice.
    ("M 50 86 L 50 52",
     "M 50 52 L 30 34",
     "M 50 52 L 70 34",
     "M 30 34 L 24 18",
     "M 30 34 L 40 20",
     "M 70 34 L 76 18",
     "M 70 34 L 60 20"),
    # F Atlas - one triangle over two.
    ("M 50 14 L 64 40 L 36 40 Z",
     "M 30 48 L 44 74 L 16 74 Z",
     "M 70 48 L 84 74 L 56 74 Z"),
)


def glyph_index(digit: str) -> int | None:
    """0..15 for one hex digit in either case, None for anything else (never raises: it reads user input)."""
    if not isinstance(digit, str) or len(digit) != 1 or digit not in "0123456789abcdefABCDEF":
        return None
    return int(digit, 16)


def _checked(index: int) -> int:
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index <= 15:
        raise IndexError(f"glyph index {index!r} is not 0..15")
    return index


def glyph_asset_names(index: int) -> tuple[str, str]:
    """The (svg, png) file names of one glyph, as both hosts reference them."""
    digit = f"{_checked(index):x}"
    return (f"glyph-{GLYPH_ART_VERSION}-{digit}.svg", f"glyph-{GLYPH_ART_VERSION}-{digit}.png")


def glyph_name(index: int) -> str:
    """The community's English name of a glyph ("Sunset"), from the table the chat answers already use."""
    from . import craftable

    return craftable.GLYPHS[_checked(index)]


def glyph_svg(index: int) -> str:
    """One glyph as a standalone <svg> string: stroke-only, currentColor, the 0..100 box."""
    paths = "".join(f'<path d="{d}"/>' for d in GLYPHS[_checked(index)])
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="none" '
            f'stroke="currentColor" stroke-width="{STROKE_WIDTH:g}" stroke-linecap="round" '
            f'stroke-linejoin="round">{paths}</svg>')
