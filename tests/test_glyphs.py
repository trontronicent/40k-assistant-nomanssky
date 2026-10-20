"""Turning a portal address into glyphs, and putting the generated files in the assets folder."""
from nms_connector import glyph_art, glyphs


def test_glyph_digits_accepts_a_full_address():
    """A twelve-digit address in either case becomes its twelve glyph indices - this is the whole translation
    the player would otherwise do in their head."""
    assert glyphs.glyph_digits("006202925E80") == [0, 0, 6, 2, 0, 2, 9, 2, 5, 14, 8, 0]
    assert glyphs.glyph_digits("006202925e80") == glyphs.glyph_digits("006202925E80")


def test_glyph_digits_refuses_anything_that_is_not_an_address():
    """Empty, too long, prefixed or non-hex input returns None, so a call site simply omits the key and the
    player still sees the plain hex instead of a broken row of symbols."""
    for bad in ("", "0062029 25E80", "006202925E801", "0x006202", "ZZZ", None, 12):
        assert glyphs.glyph_digits(bad) is None


def test_glyph_digits_accepts_a_short_address():
    """Some places show fewer than twelve digits; up to twelve is valid, so a partial address still gets its
    symbols rather than nothing."""
    assert glyphs.glyph_digits("0F") == [0, 15]


def test_ensure_glyph_assets_writes_both_formats(tmp_path):
    """The folder ends up with one SVG and one PNG per glyph, named by the art version, because the page and
    the overlay fetch them by exactly those names."""
    written = glyphs.ensure_glyph_assets(tmp_path)
    assert written == 32
    for index in range(16):
        svg, png = glyph_art.glyph_asset_names(index)
        assert (tmp_path / svg).read_text(encoding="utf-8").startswith("<svg ")
        assert (tmp_path / png).stat().st_size > 0


def test_ensure_glyph_assets_is_idempotent(tmp_path):
    """A second call writes nothing: the files are generated once per art version, not on every start."""
    glyphs.ensure_glyph_assets(tmp_path)
    assert glyphs.ensure_glyph_assets(tmp_path) == 0


def test_ensure_glyph_assets_clears_an_older_version(tmp_path):
    """Files of a superseded GLYPH_ART_VERSION are removed, so edited artwork cannot leave a stale picture
    behind in the assets folder."""
    stale = tmp_path / f"glyph-{glyph_art.GLYPH_ART_VERSION - 1}-a.png"
    stale.write_bytes(b"old")
    keep = tmp_path / "carbon.png"
    keep.write_bytes(b"not a glyph")
    glyphs.ensure_glyph_assets(tmp_path)
    assert not stale.exists()
    assert keep.exists(), "only glyph files of other versions are cleared"


def test_ensure_glyph_assets_survives_a_broken_folder(tmp_path):
    """A folder that cannot be written logs a warning and returns 0 rather than raising - losing the symbols
    must never cost the plugin its view."""
    blocked = tmp_path / "file-not-a-folder"
    blocked.write_text("x", encoding="utf-8")
    assert glyphs.ensure_glyph_assets(blocked) == 0
