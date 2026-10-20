"""The vector glyph artwork: the path model and the SVG emitter."""
import re

import pytest

from nms_connector import glyph_art


def test_glyph_index_reads_one_hex_digit():
    """A hex digit in either case is its own value, anything else is None - this is what maps an address
    character to a glyph, so a wrong answer would show the player the wrong symbol."""
    assert glyph_art.glyph_index("0") == 0
    assert glyph_art.glyph_index("f") == 15
    assert glyph_art.glyph_index("F") == 15
    assert glyph_art.glyph_index("A") == 10
    for bad in ("g", "", "10", "#", " "):
        assert glyph_art.glyph_index(bad) is None


def test_svg_is_well_formed_and_stroke_only():
    """Every glyph emits an <svg> with the 0..100 viewBox, strokes in currentColor and no fill. The page
    themes the glyphs by text colour, so a stray fill would make one glyph a black blob in dark mode."""
    for index in range(16):
        svg = glyph_art.glyph_svg(index)
        assert svg.startswith("<svg ") and svg.endswith("</svg>")
        assert 'viewBox="0 0 100 100"' in svg
        assert 'stroke="currentColor"' in svg
        assert 'fill="none"' in svg
        assert "<path" in svg


def test_svg_is_deterministic():
    """The same glyph emits the same bytes every time, so the generated asset files are stable and a
    rebuild does not churn the assets folder."""
    assert glyph_art.glyph_svg(3) == glyph_art.glyph_svg(3)


def test_every_glyph_has_paths_in_range():
    """All sixteen glyphs exist and every coordinate sits inside the 0..100 box; a stray coordinate would be
    clipped by the viewBox and silently lose part of a symbol."""
    assert len(glyph_art.GLYPHS) == 16
    for index, subpaths in enumerate(glyph_art.GLYPHS):
        assert subpaths, f"glyph {index:X} has no paths"
        for number in re.findall(r"-?\d+(?:\.\d+)?", " ".join(subpaths)):
            assert 0 <= float(number) <= 100, f"glyph {index:X}: {number} is outside the box"


def test_asset_names_carry_the_art_version():
    """The generated file names include GLYPH_ART_VERSION, so editing a shape invalidates the old files
    instead of leaving a stale picture in the assets folder."""
    svg, png = glyph_art.glyph_asset_names(10)
    assert svg == f"glyph-{glyph_art.GLYPH_ART_VERSION}-a.svg"
    assert png == f"glyph-{glyph_art.GLYPH_ART_VERSION}-a.png"


def test_glyph_index_out_of_range_is_refused():
    """An index outside 0..15 raises rather than wrapping around to another glyph."""
    with pytest.raises(IndexError):
        glyph_art.glyph_svg(16)
