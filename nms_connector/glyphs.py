"""Portal addresses as glyphs, and the generated glyph files in the plugin's assets folder.

A portal address is twelve hex digits in the save and twelve symbols in the game. ``glyph_digits`` is the only
place that decides whether a string is an address; every call site uses it and simply omits the ``glyphs`` key
when it says no, so a malformed address costs the player nothing but the symbols.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from .glyph_art import GLYPH_ART_VERSION, glyph_asset_names, glyph_index, glyph_svg
from .glyph_raster import glyph_png

logger = logging.getLogger(__name__)

MAX_DIGITS = 12
PNG_SIZE = 64                                          # the overlay subsamples 64 px icons to 21 px
ADDRESS_RE = re.compile(r"^[0-9A-Fa-f]{1,12}$")
#: Any version's generated glyph file - used to clear the files of a superseded GLYPH_ART_VERSION.
GLYPH_FILE_RE = re.compile(r"^glyph-(\d+)-[0-9a-f]\.(svg|png)$")


def glyph_digits(address: object) -> list[int] | None:
    """The glyph indices of a portal address, or None when it is not one (1..12 hex digits)."""
    if not isinstance(address, str) or not ADDRESS_RE.match(address):
        return None
    return [index for index in (glyph_index(c) for c in address) if index is not None]


def _clear_old(assets_dir: Path) -> None:
    """Remove generated glyph files of any other art version; other assets (item icons) are left alone."""
    for path in assets_dir.iterdir():
        found = GLYPH_FILE_RE.match(path.name)
        if found and int(found.group(1)) != GLYPH_ART_VERSION:
            try:
                path.unlink()
            except OSError as err:
                logger.debug("[NMS] stale glyph %s could not be removed: %s", path.name, err)


def ensure_glyph_assets(assets_dir: Path) -> int:
    """Write the generated glyph files for the current art version if they are missing, clear older ones, and
    return how many files were written. Never raises: without the files the hosts fall back to plain text."""
    written = 0
    try:
        assets_dir.mkdir(parents=True, exist_ok=True)
        _clear_old(assets_dir)
        for index in range(16):
            svg_name, png_name = glyph_asset_names(index)
            svg_path, png_path = assets_dir / svg_name, assets_dir / png_name
            if not svg_path.exists():
                svg_path.write_text(glyph_svg(index), encoding="utf-8")
                written += 1
            if not png_path.exists():
                glyph_png(index, PNG_SIZE).save(png_path, "PNG")
                written += 1
    except OSError as err:
        logger.warning("[NMS] glyph assets could not be written to %s: %s", assets_dir, err)
    return written
