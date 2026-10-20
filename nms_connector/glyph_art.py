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
STROKE_WIDTH = 5.0

#: Glyph index -> its subpaths, in a 0..100 box. The index is the value of the address digit, so this lines up
#: with ``craftable.GLYPHS`` (0 Sunset ... F Atlas) and there is no second ordering to keep in step.
#: Drawn after the game's symbols; simplified to read at 20 px, which is the size the page and the overlay use.
GLYPHS: tuple[tuple[str, ...], ...] = (
    # 0 Sunset - a dome over three waves.
    ("M 12 52 C 12 20 88 20 88 52",
     "M 14 66 C 26 58 32 74 44 66 C 56 58 62 74 74 66 C 80 62 83 63 86 66",
     "M 20 82 C 31 74 37 90 48 82 C 57 76 63 84 70 82"),
    # 1 Bird - a swept wing over a tapering body.
    ("M 10 40 C 36 24 66 26 92 42 C 66 58 34 60 14 50 Z",
     "M 28 46 C 44 40 60 40 76 44",
     "M 34 54 C 48 50 60 50 72 50",
     "M 10 40 C 4 46 6 54 14 50"),
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
    ("M 50 10 C 72 28 86 42 86 56 C 86 76 70 92 50 92 C 30 92 14 76 14 56 C 14 42 28 28 50 10 Z",
     "M 50 22 L 50 84"),
    # 6 Boat - a hull with a mast and two yards.
    ("M 12 66 C 30 84 70 84 88 66 Z",
     "M 46 20 L 46 66",
     "M 46 28 L 72 36",
     "M 46 44 L 66 50",
     "M 46 16"),
    # 7 Bug - two horns over a segmented body.
    ("M 24 16 C 18 32 24 44 36 48",
     "M 76 16 C 82 32 76 44 64 48",
     "M 50 44 L 50 72",
     "M 32 56 L 68 56",
     "M 28 84 C 36 72 64 72 72 84"),
    # 8 Dragonfly - wings across a long tail.
    ("M 50 14 L 50 88",
     "M 45 34 C 28 26 12 32 8 44 C 22 54 38 50 45 42 Z",
     "M 55 34 C 72 26 88 32 92 44 C 78 54 62 50 55 42 Z",
     "M 40 62 L 60 62",
     "M 43 74 L 57 74"),
    # 9 Galaxy - two spiral arms around a core.
    ("M 53 45 C 44 28 50 14 68 10 C 64 30 60 38 54 46 Z",
     "M 47 55 C 56 72 50 86 32 90 C 36 70 40 62 46 54 Z",
     "M 38 34 C 22 40 14 52 18 66",
     "M 62 66 C 78 60 86 48 82 34",
     "M 50 50"),
    # A Voxel - a hexagon with a dot.
    ("M 50 14 L 84 33 L 84 67 L 50 86 L 16 67 L 16 33 Z",
     "M 49 34 L 51 34"),
    # B Fish - a body with a tail and a fin.
    ("M 10 52 C 28 38 54 36 70 46 C 76 40 84 36 92 34 C 86 44 86 60 92 70 C 84 68 76 64 70 58 C 54 68 28 66 10 52 Z",
     "M 40 40 L 48 28 L 56 42",
     "M 22 50"),
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
