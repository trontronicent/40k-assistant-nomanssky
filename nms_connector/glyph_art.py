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

#: Glyph index -> its subpaths. The index is the value of the address digit, so this lines up with
#: ``craftable.GLYPHS`` (0 Sunset ... F Atlas) and there is no second ordering to keep in step.
GLYPHS: tuple[tuple[str, ...], ...] = tuple(
    (f"M 20 {20 + i} L 80 {20 + i} L 50 80 Z",) for i in range(16)
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


def glyph_svg(index: int) -> str:
    """One glyph as a standalone <svg> string: stroke-only, currentColor, the 0..100 box."""
    paths = "".join(f'<path d="{d}"/>' for d in GLYPHS[_checked(index)])
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="none" '
            f'stroke="currentColor" stroke-width="{STROKE_WIDTH:g}" stroke-linecap="round" '
            f'stroke-linejoin="round">{paths}</svg>')
