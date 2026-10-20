"""The PNG side of the glyph artwork: the path parser, the bezier flattener and the rasteriser."""
import pytest

from nms_connector import glyph_art, glyph_raster


def test_parse_path_reads_the_four_commands():
    """M/L/C/Z are the only commands the artwork uses; the parser turns one subpath into its points so the
    rasteriser never needs a general SVG parser."""
    points = glyph_raster.parse_path("M 0 0 L 10 0 C 10 10 0 10 0 0 Z")
    assert points[0] == (0.0, 0.0)
    assert (10.0, 0.0) in points
    assert points[-1] == points[0], "Z closes the subpath"


def test_parse_path_refuses_an_unknown_command():
    """An arc or a relative command would be silently mis-drawn, so the parser raises instead - this only
    ever fires on artwork we wrote ourselves, so it is a developer error, not user input."""
    with pytest.raises(ValueError):
        glyph_raster.parse_path("M 0 0 A 10 10 0 0 1 10 10")


def test_flatten_cubic_starts_and_ends_on_its_anchors():
    """A flattened curve keeps its endpoints exactly, so neighbouring segments still meet and the stroke has
    no gap at a join."""
    points = glyph_raster.flatten_cubic((0, 0), (0, 10), (10, 10), (10, 0), steps=8)
    assert points[0] == (0.0, 0.0)
    assert points[-1] == (10.0, 0.0)
    assert len(points) == 9


def test_glyph_png_has_ink_and_is_transparent():
    """Every glyph rasterises to a transparent image with strokes in it. A blank image would show the player
    an empty slot where a symbol belongs."""
    for index in range(16):
        image = glyph_raster.glyph_png(index, 64)
        assert image.size == (64, 64)
        assert image.mode == "RGBA"
        alpha = image.getchannel("A")
        assert alpha.getextrema()[1] > 200, f"glyph {index:X} has no ink"
        assert alpha.getextrema()[0] == 0, f"glyph {index:X} has no transparent background"


def test_the_sixteen_pngs_are_different():
    """Two digits must never rasterise to the same picture - the shapes are distinct, and this proves the
    rasteriser keeps them distinct."""
    seen = {}
    for index in range(16):
        data = glyph_raster.glyph_png(index, 32).tobytes()
        assert data not in seen, f"glyph {index:X} rasterises like {seen[data]:X}"
        seen[data] = index


def test_glyph_png_is_deterministic():
    """The same glyph rasterises to the same bytes, so the generated files are stable across restarts."""
    assert glyph_raster.glyph_png(7, 32).tobytes() == glyph_raster.glyph_png(7, 32).tobytes()


def test_glyph_png_refuses_a_silly_size():
    """A size outside 8..512 is a mistake in the caller, not something to render."""
    with pytest.raises(ValueError):
        glyph_raster.glyph_png(0, 4)
    with pytest.raises(ValueError):
        glyph_raster.glyph_png(0, 1024)


def test_art_version_is_shared():
    """The rasteriser reads the same version constant as the SVG side, so one bump invalidates both."""
    assert glyph_raster.GLYPH_ART_VERSION == glyph_art.GLYPH_ART_VERSION
