# Portal Glyph Symbols Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the twelve No Man's Sky portal symbols next to every portal address, in the app's plugin page and in the desktop overlay, from artwork this project draws itself.

**Architecture:** Sixteen glyphs are hand-authored once as stroke-only vector paths in the plugin (`nms_connector/glyph_art.py`). Two emitters turn that one table into `.svg` (for the browser, themeable with `currentColor`) and `.png` (for Tk, which cannot display SVG), both written into the plugin's assets folder. The app gains one additive contract key, `glyphs`, on table cells, `kv`/`stats` items and overlay areas, plus `.svg` asset serving.

**Tech Stack:** Python 3.11 (plugin + app backend), Pillow (rasteriser, already vendored), React (PluginView), Tkinter (overlay). Plugin tests: `python -m pytest tests` in the plugin repo. App tests: `venv\Scripts\python.exe -m pytest tests`.

**Repos:**
- Plugin: `J:\stc-repos\40k-assistant-nomanssky` — Tasks 1-4, 9, 10
- App: `J:\40k-assistant` — Tasks 5-8, 11

**Spec:** `docs/superpowers/specs/2026-10-20-portal-glyph-symbols-design.md` (plugin repo)

**Order note:** the app tasks (5-8) must land before the plugin's call sites (Task 9) are useful, but each task is independently testable and committable. Do them in number order.

---

### Task 1: The path model and the SVG emitter

**Files:**
- Create: `nms_connector/glyph_art.py`
- Test: `tests/test_glyph_art.py`

A glyph is a tuple of subpath strings, each using only `M`, `L`, `C` and `Z` in a `0..100` box. Keeping the data as
path strings means the SVG emitter is a join and only the rasteriser needs a parser.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /d J:\stc-repos\40k-assistant-nomanssky && python -m pytest tests/test_glyph_art.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nms_connector.glyph_art'`

- [ ] **Step 3: Write the module with a placeholder art table**

Create `nms_connector/glyph_art.py`. Task 2 replaces `GLYPHS` with the real artwork; this step uses sixteen
distinguishable stand-ins so the emitter can be tested on its own.

```python
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


def glyph_asset_names(index: int) -> tuple[str, str]:
    """The (svg, png) file names of one glyph, as both hosts reference them."""
    digit = f"{_checked(index):x}"
    return (f"glyph-{GLYPH_ART_VERSION}-{digit}.svg", f"glyph-{GLYPH_ART_VERSION}-{digit}.png")


def _checked(index: int) -> int:
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index <= 15:
        raise IndexError(f"glyph index {index!r} is not 0..15")
    return index


def glyph_svg(index: int) -> str:
    """One glyph as a standalone <svg> string: stroke-only, currentColor, the 0..100 box."""
    paths = "".join(f'<path d="{d}"/>' for d in GLYPHS[_checked(index)])
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="none" '
            f'stroke="currentColor" stroke-width="{STROKE_WIDTH:g}" stroke-linecap="round" '
            f'stroke-linejoin="round">{paths}</svg>')
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /d J:\stc-repos\40k-assistant-nomanssky && python -m pytest tests/test_glyph_art.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add nms_connector/glyph_art.py tests/test_glyph_art.py
git commit -m "feat(glyphs): the path model and the SVG emitter"
```

---

### Task 2: The sixteen glyph shapes

**Files:**
- Modify: `nms_connector/glyph_art.py` (replace the placeholder `GLYPHS`)
- Test: `tests/test_glyph_art.py` (add the distinctness test)

The shapes are drawn after the game's symbols and keep the names the plugin already uses in
`craftable.GLYPHS`: 0 Sunset, 1 Bird, 2 Face, 3 Diplo, 4 Eclipse, 5 Balloon, 6 Boat, 7 Bug, 8 Dragonfly,
9 Galaxy, A Voxel, B Fish, C Tent, D Rocket, E Tree, F Atlas.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_glyph_art.py`:

```python
def test_the_sixteen_shapes_are_all_different():
    """No two glyphs share their artwork. A copy-pasted entry would show the player the wrong symbol for a
    digit, which is the one failure this feature must never have."""
    seen = {}
    for index, subpaths in enumerate(glyph_art.GLYPHS):
        key = tuple(subpaths)
        assert key not in seen, f"glyph {index:X} has the same art as {seen[key]:X}"
        seen[key] = index


def test_each_glyph_is_named_by_the_existing_table():
    """glyph_name reuses craftable.GLYPHS, so the names in a tooltip, an alt text and a chat answer can
    never drift apart."""
    from nms_connector import craftable

    assert glyph_art.glyph_name(0) == "Sunset"
    assert glyph_art.glyph_name(15) == "Atlas"
    assert [glyph_art.glyph_name(i) for i in range(16)] == list(craftable.GLYPHS)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /d J:\stc-repos\40k-assistant-nomanssky && python -m pytest tests/test_glyph_art.py -v`
Expected: FAIL — `test_the_sixteen_shapes_are_all_different` passes by luck on the stand-ins, but
`test_each_glyph_is_named_by_the_existing_table` fails with `AttributeError: module 'nms_connector.glyph_art' has no attribute 'glyph_name'`

- [ ] **Step 3: Replace `GLYPHS` with the artwork and add `glyph_name`**

In `nms_connector/glyph_art.py`, replace the placeholder `GLYPHS` assignment with the table below, and add
`glyph_name` under it.

```python
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


def glyph_name(index: int) -> str:
    """The community's English name of a glyph ("Sunset"), from the table the chat answers already use."""
    from . import craftable

    return craftable.GLYPHS[_checked(index)]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /d J:\stc-repos\40k-assistant-nomanssky && python -m pytest tests/test_glyph_art.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Eyeball the artwork**

The tests prove the shapes are valid and distinct, not that they are recognisable. Write the sixteen SVGs into
one page and open it:

```bash
python -c "from nms_connector import glyph_art as g; open('glyphs.html','w').write('<body style=\"background:#111;color:#e8c87a\">' + ''.join(f'<span style=\"display:inline-block;width:90px;text-align:center\"><span style=\"display:block;width:72px;height:72px\">{g.glyph_svg(i)}</span>{i:X} {g.glyph_name(i)}</span>' for i in range(16)))"
start glyphs.html
```

Expected: sixteen distinguishable symbols, each readable at the small size. Adjust coordinates in `GLYPHS` and
re-run until they read well, then delete `glyphs.html` (do not commit it).

- [ ] **Step 6: Commit**

```bash
git add nms_connector/glyph_art.py tests/test_glyph_art.py
git commit -m "feat(glyphs): the sixteen glyph shapes"
```

---

### Task 3: The PNG rasteriser

**Files:**
- Create: `nms_connector/glyph_raster.py`
- Test: `tests/test_glyph_raster.py`

Tk cannot display SVG, so the overlay needs PNGs. Pillow has no bezier primitive, so each `C` segment is
flattened to a polyline; the whole glyph is drawn at 4x and downsampled, which is how the strokes come out
smooth without an anti-aliasing library.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /d J:\stc-repos\40k-assistant-nomanssky && python -m pytest tests/test_glyph_raster.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nms_connector.glyph_raster'`

- [ ] **Step 3: Write the rasteriser**

```python
"""The glyph artwork as PNGs, for the overlay.

The page gets SVG, but the overlay is Tk, which displays PNG and GIF only - and neither the app's environment
nor this plugin's vendored runtime has an SVG rasteriser (cairosvg, svglib, skia, aggdraw are all absent).
Pillow is there, so the same paths are drawn here: every cubic segment is flattened to a polyline (Pillow has
no bezier primitive), and the glyph is drawn at SUPERSAMPLE times the wanted size and downsampled, which is
what makes the strokes smooth without an anti-aliasing library.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from .glyph_art import GLYPH_ART_VERSION, GLYPHS, STROKE_WIDTH, _checked

BOX = 100.0              # the artwork's coordinate box
SUPERSAMPLE = 4          # drawn this many times larger, then downsampled with LANCZOS
CURVE_STEPS = 16         # segments per cubic; at 20 px on screen the corners are already invisible
MIN_SIZE, MAX_SIZE = 8, 512

Point = tuple[float, float]


def flatten_cubic(p0: Point, p1: Point, p2: Point, p3: Point, steps: int = CURVE_STEPS) -> list[Point]:
    """A cubic bezier as `steps` + 1 points, the endpoints kept exactly so neighbouring segments still meet."""
    out: list[Point] = []
    for i in range(steps + 1):
        t = i / steps
        u = 1.0 - t
        x = u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0]
        y = u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]
        out.append((x, y))
    out[0], out[-1] = (float(p0[0]), float(p0[1])), (float(p3[0]), float(p3[1]))
    return out


def parse_path(d: str) -> list[Point]:
    """One subpath string as the points of its polyline. Only M, L, C and Z occur in our own artwork; anything
    else raises, because a silently mis-drawn glyph is worse than a failing test."""
    tokens = d.replace(",", " ").split()
    points: list[Point] = []
    start: Point | None = None
    i = 0
    while i < len(tokens):
        command = tokens[i]
        i += 1
        if command == "Z":
            if start is not None:
                points.append(start)
            continue
        if command not in ("M", "L", "C"):
            raise ValueError(f"unsupported path command {command!r} in {d!r}")
        count = 6 if command == "C" else 2
        numbers = [float(n) for n in tokens[i:i + count]]
        if len(numbers) != count:
            raise ValueError(f"{command} needs {count} numbers in {d!r}")
        i += count
        if command == "C":
            here = points[-1] if points else (0.0, 0.0)
            points.extend(flatten_cubic(here, (numbers[0], numbers[1]), (numbers[2], numbers[3]),
                                        (numbers[4], numbers[5]))[1:])
        else:
            points.append((numbers[0], numbers[1]))
            if command == "M":
                start = (numbers[0], numbers[1])
    return points


def glyph_png(index: int, size: int) -> Image.Image:
    """One glyph as a transparent RGBA image of `size` x `size`, strokes in white (the overlay tints nothing,
    so white is what its dark background wants)."""
    if not isinstance(size, int) or isinstance(size, bool) or not MIN_SIZE <= size <= MAX_SIZE:
        raise ValueError(f"glyph size {size!r} is not {MIN_SIZE}..{MAX_SIZE}")
    big = size * SUPERSAMPLE
    scale = big / BOX
    image = Image.new("RGBA", (big, big), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    width = max(1, round(STROKE_WIDTH * scale))
    for subpath in GLYPHS[_checked(index)]:
        points = [(x * scale, y * scale) for x, y in parse_path(subpath)]
        if len(points) > 1:
            draw.line(points, fill=(255, 255, 255, 255), width=width, joint="curve")
        elif points:                       # a single M is a dot (the Face's eyes, the Voxel's mark)
            x, y = points[0]
            draw.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2),
                         fill=(255, 255, 255, 255))
    return image.resize((size, size), Image.LANCZOS)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /d J:\stc-repos\40k-assistant-nomanssky && python -m pytest tests/test_glyph_raster.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add nms_connector/glyph_raster.py tests/test_glyph_raster.py
git commit -m "feat(glyphs): rasterise the artwork to PNG for the overlay"
```

---

### Task 4: Addresses to glyphs, and writing the assets

**Files:**
- Create: `nms_connector/glyphs.py`
- Test: `tests/test_glyphs.py`

- [ ] **Step 1: Write the failing test**

```python
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


def test_ensure_glyph_assets_survives_a_broken_folder(tmp_path, caplog):
    """A folder that cannot be written logs a warning and returns 0 rather than raising - losing the symbols
    must never cost the plugin its view."""
    blocked = tmp_path / "file-not-a-folder"
    blocked.write_text("x", encoding="utf-8")
    assert glyphs.ensure_glyph_assets(blocked) == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /d J:\stc-repos\40k-assistant-nomanssky && python -m pytest tests/test_glyphs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nms_connector.glyphs'`

- [ ] **Step 3: Write the module**

```python
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


def _clear_old(assets_dir: Path) -> None:
    """Remove generated glyph files of any other art version; other assets (item icons) are left alone."""
    for path in assets_dir.iterdir():
        found = GLYPH_FILE_RE.match(path.name)
        if found and int(found.group(1)) != GLYPH_ART_VERSION:
            try:
                path.unlink()
            except OSError as err:
                logger.debug("[NMS] stale glyph %s could not be removed: %s", path.name, err)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /d J:\stc-repos\40k-assistant-nomanssky && python -m pytest tests/test_glyphs.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add nms_connector/glyphs.py tests/test_glyphs.py
git commit -m "feat(glyphs): addresses to glyphs, and the generated assets"
```

---

### Task 5: The app keeps a `glyphs` key

**Files:**
- Modify: `J:\40k-assistant\src\plugins\views.py` (`ICON_NAME_RE` at :137, `_table_cell` at :157, `_labelled` at :187, the module docstring at :15-40)
- Test: `J:\40k-assistant\tests\test_plugins_views.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_plugins_views.py`:

```python
def test_table_cell_keeps_a_portal_address_as_glyphs():
    """A cell may carry `glyphs` (1-12 hex digits) beside its text, so the plugin page can draw the portal
    symbols next to the address the player copies."""
    view = views.normalize_view({"sections": [
        {"type": "table", "columns": ["System", "Portal"],
         "rows": [["Ulebsk", {"text": "006202925E80", "glyphs": "006202925E80"}]]}]}, "nomanssky")
    cell = view["sections"][0]["rows"][0][1]
    assert cell == {"text": "006202925E80", "glyphs": "006202925E80"}


def test_table_cell_drops_an_invalid_glyph_address_but_keeps_the_text():
    """Anything that is not 1-12 hex digits is dropped, so a mistake in the plugin shows the plain address
    rather than a row of wrong symbols."""
    for bad in ("", "ZZZZ", "0x0062", "0062029250801", 12, None, "00 62"):
        view = views.normalize_view({"sections": [
            {"type": "table", "columns": ["Portal"], "rows": [[{"text": "x", "glyphs": bad}]]}]}, "nomanssky")
        assert view["sections"][0]["rows"][0][0] == "x", f"{bad!r} should have been dropped"


def test_kv_item_keeps_glyphs():
    """'Where you are' shows the address as a kv item, so items take the key too - otherwise the one place
    the player looks most would keep plain hex."""
    view = views.normalize_view({"sections": [
        {"type": "kv", "items": [{"label": "Portal address", "value": "006202925E80",
                                  "glyphs": "006202925E80"}]}]}, "nomanssky")
    assert view["sections"][0]["items"][0]["glyphs"] == "006202925E80"


def test_kv_item_without_glyphs_is_unchanged():
    """Items that carry no address keep exactly the shape they had before this feature."""
    view = views.normalize_view({"sections": [
        {"type": "kv", "items": [{"label": "Galaxy", "value": "Euclid"}]}]}, "nomanssky")
    assert view["sections"][0]["items"][0] == {"label": "Galaxy", "value": "Euclid"}


def test_icon_name_accepts_svg_and_still_refuses_other_extensions():
    """Glyphs are served as SVG, so the asset name rule takes .svg as well - and nothing else, because the
    same rule guards the asset endpoint."""
    assert views.ICON_NAME_RE.match("glyph-1-a.svg")
    assert views.ICON_NAME_RE.match("carbon.png")
    assert not views.ICON_NAME_RE.match("evil.html")
    assert not views.ICON_NAME_RE.match("../secret.svg")
    assert not views.ICON_NAME_RE.match("evil.svg.html")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /d J:\40k-assistant && venv\Scripts\python.exe -m pytest tests/test_plugins_views.py -k "glyph or icon_name" -v`
Expected: FAIL — the cell comes back as the plain string `"006202925E80"` and `ICON_NAME_RE` does not match `.svg`

- [ ] **Step 3: Implement**

In `src/plugins/views.py`:

```python
# Icon file names a view may reference (also enforced by the asset endpoint). SVG is allowed since the glyph
# artwork is vector; such a file is only ever loaded inside an <img>, where script inside an SVG does not run.
ICON_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}\.(png|svg)$")
# A portal address a cell or item wants drawn as glyphs: 1-12 hex digits, nothing else.
GLYPH_ADDRESS_RE = re.compile(r"^[0-9A-Fa-f]{1,12}$")
```

Add this helper above `_table_cell`:

```python
def _glyphs(value: object) -> str | None:
    """A portal address to draw as glyphs, or None. Shared by table cells and kv/stats items."""
    return value if isinstance(value, str) and GLYPH_ADDRESS_RE.match(value) else None
```

In `_table_cell`, after the `icon` block:

```python
        address = _glyphs(value.get("glyphs"))
        if address:
            out["glyphs"] = address
```

In `_labelled`, after the `hint` block:

```python
        address = _glyphs(item.get("glyphs"))
        if address:
            entry["glyphs"] = address
```

Update the module docstring's example at the top so the shape is documented where the others are:

```python
        {"type": "kv",    "title": "...", "items": [{"label": "Portal address", "value": "006202925E80",
                                                     "glyphs": "006202925E80"}]},
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /d J:\40k-assistant && venv\Scripts\python.exe -m pytest tests/test_plugins_views.py -v`
Expected: PASS (the whole file, including the tests that were already there)

- [ ] **Step 5: Commit**

```bash
git add src/plugins/views.py tests/test_plugins_views.py
git commit -m "feat(plugins): a view cell or item may carry a portal address as glyphs"
```

---

### Task 6: The asset route serves SVG

**Files:**
- Modify: `J:\40k-assistant\src\plugins\manager.py:186-200` (`asset_path`)
- Modify: the asset endpoint in `J:\40k-assistant\src\plugins\router.py` (find it with `grep -n "assets" src/plugins/router.py`)
- Test: `J:\40k-assistant\tests\test_plugins_api.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_plugins_api.py` (follow the file's existing fixture for an installed plugin with an assets
folder; the assertions below are what matters):

```python
def test_assets_endpoint_serves_svg_with_its_own_type(client, installed_plugin_with_assets):
    """Glyphs are SVG, so the route must serve them as image/svg+xml - a wrong type makes the browser
    download the file instead of drawing the symbol."""
    (installed_plugin_with_assets / "glyph-1-a.svg").write_text("<svg/>", encoding="utf-8")
    res = client.get("/plugins/nomanssky/assets/glyph-1-a.svg")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/svg+xml")
    assert res.headers["x-content-type-options"] == "nosniff"


def test_assets_endpoint_still_serves_png_as_png(client, installed_plugin_with_assets):
    """The existing item icons must keep their type exactly as before this change."""
    (installed_plugin_with_assets / "carbon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    res = client.get("/plugins/nomanssky/assets/carbon.png")
    assert res.headers["content-type"].startswith("image/png")


def test_assets_endpoint_refuses_traversal_and_other_types(client, installed_plugin_with_assets):
    """Widening the name rule to .svg must not widen anything else: separators, '..' and other extensions
    stay refused."""
    for name in ("../secret.svg", "sub/dir.svg", "evil.html", "evil.svg.html"):
        assert client.get(f"/plugins/nomanssky/assets/{name}").status_code in (400, 404)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /d J:\40k-assistant && venv\Scripts\python.exe -m pytest tests/test_plugins_api.py -k assets -v`
Expected: FAIL — the SVG request 404s (the name does not match the old `ICON_NAME_RE`) or comes back as
`image/png`

- [ ] **Step 3: Implement**

`asset_path` needs no logic change — it already uses `ICON_NAME_RE`, which Task 5 widened. Update its docstring
at `manager.py:189` so it no longer says "png only":

```python
        The name must match views.ICON_NAME_RE (no separators, no '..', .png or .svg) and
```

In the router's asset endpoint, pick the media type from the suffix instead of hard-coding `image/png`:

```python
# The two asset types a plugin may serve (views.ICON_NAME_RE). An SVG is only ever loaded inside an <img>,
# where script inside it does not run; nosniff keeps the browser from reinterpreting either one.
ASSET_TYPES = {".png": "image/png", ".svg": "image/svg+xml"}
```

and at the response:

```python
    media_type = ASSET_TYPES.get(path.suffix.lower())
    if media_type is None:
        raise HTTPException(status_code=404, detail="unknown asset type")
    return FileResponse(path, media_type=media_type,
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "max-age=3600"})
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /d J:\40k-assistant && venv\Scripts\python.exe -m pytest tests/test_plugins_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/plugins/manager.py src/plugins/router.py tests/test_plugins_api.py
git commit -m "feat(plugins): the asset route serves SVG as well as PNG"
```

---

### Task 7: The page draws the glyph row

**Files:**
- Modify: `J:\40k-assistant\frontend\src\components\plugins\pluginModel.js` (`ICON_NAME_RE` at :203, add `cellGlyphs` and `GLYPH_NAMES` near `cellHint` at :162)
- Modify: `J:\40k-assistant\frontend\src\components\plugins\PluginView.jsx` (`S.cellIcon` at :70, `Cell` at :234, `KeyValues` at :221)
- Test: `J:\40k-assistant\tests\test_plugins_frontend.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_plugins_frontend.py`, following the file's existing pattern of running the pure helpers under
Node and rendering sections with SSR:

```python
def test_cell_glyphs_reads_an_address(node_helpers):
    """cellGlyphs mirrors views.GLYPH_ADDRESS_RE, so the page never tries to draw a symbol for something the
    backend would not have kept."""
    assert node_helpers("cellGlyphs({text: 'x', glyphs: '006202925E80'})") == "006202925E80"
    for bad in ("'x'", "{text: 'x'}", "{text: 'x', glyphs: 'ZZ'}", "{text: 'x', glyphs: ''}"):
        assert node_helpers(f"cellGlyphs({bad})") is None


def test_glyph_asset_name_matches_the_plugins_file_names(node_helpers):
    """The page builds the file name the plugin wrote; a mismatch means every symbol 404s."""
    assert node_helpers("glyphAssetName('e', 1)") == "glyph-1-e.svg"
    assert node_helpers("glyphAssetName('E', 1)") == "glyph-1-e.svg"


def test_a_cell_with_glyphs_renders_an_image_per_digit(render_section):
    """Twelve digits become twelve <img> tags plus the address text, so the player can read the symbols and
    still copy the hex."""
    html = render_section({"type": "table", "columns": ["Portal"],
                           "rows": [[{"text": "006202925E80", "glyphs": "006202925E80"}]]}, plugin_id="nomanssky")
    assert html.count("<img") == 12
    assert "glyph-1-0.svg" in html and "glyph-1-e.svg" in html
    assert "006202925E80" in html
    assert 'alt="Sunset"' in html


def test_a_kv_item_with_glyphs_renders_the_row(render_section):
    """'Where you are' is a kv section, so the symbols have to work there too."""
    html = render_section({"type": "kv", "items": [{"label": "Portal address", "value": "006202925E80",
                                                    "glyphs": "006202925E80"}]}, plugin_id="nomanssky")
    assert html.count("<img") == 12


def test_glyphs_without_a_plugin_id_fall_back_to_text(render_section):
    """Outside the plugin page there is no URL to build, so the address shows as text - the same rule an icon
    cell already follows."""
    html = render_section({"type": "kv", "items": [{"label": "Portal address", "value": "006202925E80",
                                                    "glyphs": "006202925E80"}]}, plugin_id=None)
    assert "<img" not in html
    assert "006202925E80" in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /d J:\40k-assistant && venv\Scripts\python.exe -m pytest tests/test_plugins_frontend.py -k glyph -v`
Expected: FAIL — `cellGlyphs is not defined`

- [ ] **Step 3: Implement**

In `pluginModel.js`, beside `cellHint`:

```js
/** Same rule as views.GLYPH_ADDRESS_RE: a portal address a cell or item wants drawn as symbols. */
export const GLYPH_ADDRESS_RE = /^[0-9A-Fa-f]{1,12}$/;

/** The art version the plugin generates its glyph files under (glyph_art.GLYPH_ART_VERSION). */
export const GLYPH_ART_VERSION = 1;

/** The community's English glyph names, in the order of the address digits 0-F (craftable.GLYPHS). */
export const GLYPH_NAMES = ['Sunset', 'Bird', 'Face', 'Diplo', 'Eclipse', 'Balloon', 'Boat', 'Bug',
  'Dragonfly', 'Galaxy', 'Voxel', 'Fish', 'Tent', 'Rocket', 'Tree', 'Atlas'];

/** The portal address of a cell or item `{text, glyphs}`, or null. */
export function cellGlyphs(value) {
  return value && typeof value === 'object' && typeof value.glyphs === 'string'
    && GLYPH_ADDRESS_RE.test(value.glyphs) ? value.glyphs : null;
}

/** The asset file name of one glyph digit, as nms_connector/glyph_art.glyph_asset_names writes it. */
export function glyphAssetName(digit, version = GLYPH_ART_VERSION) {
  return `glyph-${version}-${String(digit).toLowerCase()}.svg`;
}

/** The English name of a glyph digit, for an image's alt text. */
export function glyphName(digit) {
  return GLYPH_NAMES[parseInt(digit, 16)] || '';
}
```

and widen the asset-name rule so it still mirrors the backend:

```js
/** Same rule as views.ICON_NAME_RE / the asset endpoint. */
export const ICON_NAME_RE = /^[a-z0-9][a-z0-9._-]{0,119}\.(png|svg)$/;
```

In `PluginView.jsx`, add the styles beside `S.cellIcon`:

```js
  // A portal address drawn as its glyphs: a row of small symbols above or before the hex the player copies.
  glyphRow: { display: 'inline-flex', alignItems: 'center', gap: '2px', verticalAlign: 'middle' },
  glyphImg: { width: '20px', height: '20px', color: 'var(--gold-bright)', flexShrink: 0 },
  glyphCell: { display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' },
```

a component above `Cell`:

```jsx
/**
 * A portal address as the game's symbols. The images are the plugin's own SVG artwork, one per hex digit, and
 * they are coloured by `color` because the artwork strokes in currentColor. The address stays beside them: it
 * is what the player copies and what a screen reader gets if the images never arrive.
 */
function GlyphRow({ address }) {
  const { pluginId } = useContext(ViewContext);
  if (!pluginId) return null;
  return (
    <span style={S.glyphRow}>
      {Array.from(address).map((digit, i) => (
        <img key={i} src={pluginAssetUrl(API_BASE, pluginId, glyphAssetName(digit))} alt={glyphName(digit)}
          title={glyphName(digit)} loading="lazy" decoding="async" style={S.glyphImg}
          onError={(e) => { e.currentTarget.style.display = 'none'; }} />
      ))}
    </span>
  );
}
```

in `Cell`, after `const icon = ...`:

```jsx
  const glyphs = pluginId ? cellGlyphs(cell) : null;
```

and make the body honour it (replacing the existing `const body = ...`):

```jsx
  const body = glyphs ? (
    <span style={S.glyphCell}><GlyphRow address={glyphs} /><span>{formatCell(cell)}</span></span>
  ) : !icon ? formatCell(cell) : (
    <span style={S.iconCell}>
      <img src={pluginAssetUrl(API_BASE, pluginId, icon)} alt="" loading="lazy" decoding="async" style={S.cellIcon}
        onError={(e) => { e.currentTarget.style.visibility = 'hidden'; }} />
      <span>{formatCell(cell)}</span>
    </span>
  );
```

and in `KeyValues`, give the value the same treatment:

```jsx
function KeyValues({ items }) {
  return (
    <div className="stc-kv" style={S.kv}>
      {items.map((item, i) => (
        <React.Fragment key={i}>
          <div style={S.kvLabel}>{item.label}</div>
          <div style={S.kvValue}>
            {cellGlyphs(item) ? (
              <span style={S.glyphCell}><GlyphRow address={item.glyphs} /><span>{formatCell(item.value)}</span></span>
            ) : formatCell(item.value)}
          </div>
        </React.Fragment>
      ))}
    </div>
  );
}
```

Add `cellGlyphs`, `glyphAssetName` and `glyphName` to the import from `pluginModel` at the top of the file.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /d J:\40k-assistant && venv\Scripts\python.exe -m pytest tests/test_plugins_frontend.py -v`
Expected: PASS

- [ ] **Step 5: Check the tooltip guard still passes**

The static test that every interactive element is wrapped in a `Tooltip` also covers `PluginView.jsx`.

Run: `cd /d J:\40k-assistant && venv\Scripts\python.exe -m pytest tests/test_static_tooltips.py -v`
Expected: PASS (the glyph images are not interactive; they carry `title` and `alt`)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/plugins/pluginModel.js frontend/src/components/plugins/PluginView.jsx tests/test_plugins_frontend.py
git commit -m "feat(plugins): draw a portal address as its glyphs in the plugin page"
```

---

### Task 8: The overlay draws the glyph row

**Files:**
- Modify: `J:\40k-assistant\src\plugins\overlay.py` (`_areas` at :108-127)
- Modify: `J:\40k-assistant\src\overlay\model.py` (`Area` at :217-234, `plugin_areas` at :311-321)
- Modify: `J:\40k-assistant\src\overlay\window.py` (`_draw_timers_and_lines` at :636-651, the area branch at :603)
- Test: `J:\40k-assistant\tests\test_plugins_overlay.py` and `J:\40k-assistant\tests\test_overlay_model.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_plugins_overlay.py`:

```python
def test_an_area_keeps_a_portal_address_as_glyphs():
    """An overlay area may carry an address to draw as symbols, checked by the same rule the view uses."""
    out = overlay.normalize_overlay(
        {"areas": [{"id": "location", "title": "Where you are", "lines": ["Ulebsk"],
                    "glyphs": "006202925E80"}]}, "nomanssky", "NMS")
    assert out["areas"][0]["glyphs"] == "006202925E80"


def test_an_area_drops_an_invalid_glyph_address():
    """A malformed address leaves the area's lines untouched rather than drawing wrong symbols."""
    for bad in ("ZZZ", "", "0062029250801", 7, None):
        out = overlay.normalize_overlay(
            {"areas": [{"id": "location", "lines": ["Ulebsk"], "glyphs": bad}]}, "nomanssky", "NMS")
        assert out["areas"][0]["glyphs"] == ""
        assert out["areas"][0]["lines"] == ["Ulebsk"]
```

Add to `tests/test_overlay_model.py`:

```python
def test_plugin_areas_carry_their_glyph_address():
    """The drawable Area keeps the address, so the window can turn it into one image per digit."""
    areas = model.plugin_areas({"areas": [{"id": "location", "title": "Where you are", "lines": ["Ulebsk"],
                                           "glyphs": "006202925E80", "default_on": True}]}, None, 0.0)
    assert areas[0].glyphs == "006202925E80"


def test_glyph_icon_names_match_the_plugins_files():
    """The overlay fetches the PNG variant by the name the plugin wrote; a mismatch means no symbols."""
    assert model.glyph_icon_names("0F") == ("glyph-1-0.png", "glyph-1-f.png")
    assert model.glyph_icon_names("nope") == ()


def test_an_area_without_an_address_has_no_glyphs():
    """Areas that carry no address are exactly what they were before this feature."""
    areas = model.plugin_areas({"areas": [{"id": "timers", "lines": [], "default_on": True}]}, None, 0.0)
    assert areas[0].glyphs == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /d J:\40k-assistant && venv\Scripts\python.exe -m pytest tests/test_plugins_overlay.py tests/test_overlay_model.py -k glyph -v`
Expected: FAIL — `KeyError: 'glyphs'` and `AttributeError: 'Area' object has no attribute 'glyphs'`

- [ ] **Step 3: Implement**

In `src/plugins/overlay.py`, import the rule and keep the key. At the top, beside the other imports from
`views`:

```python
from .views import ACTION_ID_RE, FIELD_ID_RE, GLYPH_ADDRESS_RE
```

and in `_areas`, inside the appended dict:

```python
                    "glyphs": _glyph_address(item.get("glyphs")),
```

with the helper above `_areas`:

```python
def _glyph_address(value) -> str:
    """A portal address an area wants drawn as glyphs, or "" - the same rule the view's cells use."""
    return value if isinstance(value, str) and GLYPH_ADDRESS_RE.match(value) else ""
```

In `src/overlay/model.py`, add the field to `Area`:

```python
    glyphs: str = ""                        # a portal address drawn as the game's symbols above the lines
```

the art version and the name builder near the other module constants:

```python
GLYPH_ART_VERSION = 1                       # nms_connector/glyph_art.GLYPH_ART_VERSION
GLYPH_ADDRESS_RE = re.compile(r"^[0-9A-Fa-f]{1,12}$")


def glyph_icon_names(address: str) -> Tuple[str, ...]:
    """The PNG file names of a portal address's glyphs, as the plugin's glyph_art writes them; () when the
    address is not one (1-12 hex digits), so the area simply draws no symbols."""
    if not isinstance(address, str) or not GLYPH_ADDRESS_RE.match(address):
        return ()
    return tuple(f"glyph-{GLYPH_ART_VERSION}-{c.lower()}.png" for c in address)
```

and in `plugin_areas`, pass it through:

```python
                        recipes=recipe_lines(a.get("recipes")), search=a.get("search") is True,
                        glyphs=str(a.get("glyphs") or ""),
```

In `src/overlay/window.py`, add the size beside `RECIPE_ICON`:

```python
GLYPH_ICON = 21       # the glyph PNGs are 64 px, subsampled by 3 like the recipe icons
```

change the area branch at :603 to pass the address:

```python
            elif area.timers or area.lines or area.glyphs:
                y = self._draw_timers_and_lines(area.timers, area.lines, w, y, px, area.glyphs)
```

and draw the row at the top of `_draw_timers_and_lines` (new last parameter `glyphs: str = ""`), before the
timers loop:

```python
        names = glyph_icon_names(glyphs)
        if names:
            # The plugin's own glyph artwork, one PNG per digit. A symbol that has not arrived yet is simply
            # not drawn - the address is in the lines below it either way.
            self._icons.want(mode_plugin(self.settings.mode) or "", list(names))
            x = pad
            for name in names:
                image = self._icons.image(name)
                if image is not None:
                    c.create_image(x, y, image=image, anchor="nw", tags=("head", "glyph"))
                x += GLYPH_ICON + 2
            y += GLYPH_ICON + 4
```

Import `glyph_icon_names` from `.model` where `mode_plugin` is already imported.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /d J:\40k-assistant && venv\Scripts\python.exe -m pytest tests/test_plugins_overlay.py tests/test_overlay_model.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/plugins/overlay.py src/overlay/model.py src/overlay/window.py tests/test_plugins_overlay.py tests/test_overlay_model.py
git commit -m "feat(overlay): draw a plugin area's portal address as glyphs"
```

---

### Task 9: The plugin sends the key everywhere it shows an address

**Files:**
- Modify: `nms_connector/planets_view.py` (`where_you_are` at :625-645, the system-map star at :647-665, the visited-systems row at :779, the route result at :1279, the starmap point at :936)
- Modify: `nms_connector/companion.py` (`overlay()` at :431)
- Modify: `nms_connector/plugin.py` (call `ensure_glyph_assets` where `_ensure_icons` is called at start)
- Test: `tests/test_glyph_call_sites.py`

- [ ] **Step 1: Write the failing test**

```python
"""Every place that shows a portal address also sends it as glyphs."""
from nms_connector import glyphs, planets_view


def test_where_you_are_sends_the_address_as_glyphs(context_with_location):
    """The one place the player looks most: the address keeps its text and gains the symbols."""
    section = planets_view.where_you_are(context_with_location)
    item = next(i for i in section["items"] if i["label"] == "Portal address")
    assert item["value"] == item["glyphs"]
    assert glyphs.glyph_digits(item["glyphs"]) is not None


def test_the_system_map_star_sends_the_address_as_glyphs(context_with_location):
    """The star of a system map carries the same address, so it gets the same symbols."""
    section = planets_view.system_map(context_with_location, context_with_location.current_key)
    item = next(i for i in section["center"]["items"] if i["label"] == "Portal address")
    assert item["glyphs"] == item["value"]


def test_an_item_without_an_address_sends_no_glyphs(context_with_location):
    """Only the address items gain the key; everything else is byte-identical to before."""
    section = planets_view.where_you_are(context_with_location)
    for item in section["items"]:
        if item["label"] != "Portal address":
            assert "glyphs" not in item


def test_the_overlay_location_area_sends_the_address(companion_with_location):
    """The overlay's location area carries the address, which is what its glyph row draws."""
    area = next(a for a in companion_with_location.overlay()["areas"] if a["id"] == "location")
    assert glyphs.glyph_digits(area["glyphs"]) is not None
```

Reuse the fixtures the existing `tests/test_planets_view.py` and `tests/test_connector.py` already build for a
context with a known location; add `context_with_location` and `companion_with_location` to `tests/conftest.py`
if they are not already there, built from the same sample save those tests use.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /d J:\stc-repos\40k-assistant-nomanssky && python -m pytest tests/test_glyph_call_sites.py -v`
Expected: FAIL — `KeyError: 'glyphs'`

- [ ] **Step 3: Implement**

Add a small helper at the top of `planets_view.py`, so no call site repeats the check:

```python
from .glyphs import glyph_digits


def portal_item(label: str, address: str | None) -> dict:
    """A kv item for a portal address, with the address also sent as glyphs when it is one. The text stays:
    it is what the player copies, and it is the fallback when the symbols cannot be drawn."""
    item = {"label": label, "value": address or "–"}
    if address and glyph_digits(address):
        item["glyphs"] = address
    return item
```

Replace each `{"label": "Portal address", "value": address_portal(addr)}` (at :638 and :661) with:

```python
        portal_item("Portal address", address_portal(addr)),
```

For the visited-systems table (:779) and the route result (:1279), wrap the address cell the same way:

```python
def portal_cell(address: str | None) -> object:
    """A table cell for a portal address: the text, plus the glyphs when it is a valid address."""
    if address and glyph_digits(address):
        return {"text": address, "glyphs": address}
    return address or "–"
```

and use `portal_cell(address_portal(addr))` where the bare `address_portal(addr)` was the cell.

In `companion.py`'s `overlay()`, add the address to the location area:

```python
            "glyphs": portal or "",
```

where `portal` is the address that area's lines already show.

In `plugin.py`, beside the existing icon preparation at start:

```python
        # The glyph artwork is generated once per art version, in a thread like the item icons - the page and
        # the overlay fetch it from the assets folder by name.
        await self.ctx.run_blocking(ensure_glyph_assets, self.ctx.assets_dir)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /d J:\stc-repos\40k-assistant-nomanssky && python -m pytest tests/test_glyph_call_sites.py -v`
Expected: PASS

- [ ] **Step 5: Run the plugin's whole suite**

Run: `cd /d J:\stc-repos\40k-assistant-nomanssky && python -m pytest tests -q`
Expected: PASS — in particular `tests/test_host_contract.py`, which holds the standalone host to the same
view/overlay shapes

- [ ] **Step 6: Commit**

```bash
git add nms_connector/planets_view.py nms_connector/companion.py nms_connector/plugin.py tests/test_glyph_call_sites.py tests/conftest.py
git commit -m "feat(glyphs): send the portal address as glyphs from every place that shows one"
```

---

### Task 10: Check it in the running app

**Files:** none (verification)

Unit tests cannot show whether the symbols are recognisable or the row is the right size. This task is the
real check, and it is the one that decides whether the artwork needs another pass.

- [ ] **Step 1: Install the plugin's changes into the app**

The app runs the installed copy in `plugins/nomanssky/`, never the repository.

```bash
cd /d J:\40k-assistant
venv\Scripts\python.exe tools/sync_plugin.py J:\stc-repos\40k-assistant-nomanssky
```

Expected: the manifest loader validates and the old copy moves to `plugins/.trash/`

- [ ] **Step 2: Rebuild the frontend**

```bash
cd /d J:\40k-assistant\frontend && npm run build
```

Expected: a clean build (a stale `frontend/dist` is served as-is)

- [ ] **Step 3: Restart the backend and open the plugin page**

Check *Overview → Where you are*, the Systems tab's visited-systems table and the system map's star. Expected:
twelve symbols beside each address, each about 20 px, in the UI's gold, with the hex still readable beside them,
and the glyph's name in the tooltip when hovering one.

- [ ] **Step 4: Check the overlay**

Open the desktop overlay in the plugin's mode with the location area on. Expected: the same twelve symbols in
white above the location lines.

- [ ] **Step 5: Compare against the game**

With the game running, open the galaxy map and compare the symbols against the address the game shows for the
current system. Expected: the same twelve symbols in the same order. If one is hard to recognise, fix its entry
in `GLYPHS`, bump `GLYPH_ART_VERSION`, bump `GLYPH_ART_VERSION` in `pluginModel.js` and `src/overlay/model.py`
to match, and repeat from Step 1.

- [ ] **Step 6: Commit any artwork fixes**

```bash
git add nms_connector/glyph_art.py
git commit -m "fix(glyphs): the shapes as the game draws them"
```

---

### Task 11: Documentation and versions

**Files:**
- Modify: `J:\40k-assistant\docs\architecture\plugins.md`
- Modify: `J:\40k-assistant\frontend\src\manual\USER_MANUAL.md`
- Modify: `J:\40k-assistant\features.md`
- Modify: `J:\40k-assistant\src\main.py` (the FastAPI version = `compat.APP_VERSION`)
- Modify: `nms_connector/credits.py`, `CHANGELOG.md`, `HELP.md`, `features.md`, `strategicum-plugin.json` (plugin repo)

- [ ] **Step 1: Document the contract in the app**

Add a bullet to `docs/architecture/plugins.md` in the same style as the ones around it:

> **Portal glyphs (app 3.20.0).** A table cell, a `kv`/`stats` item and an overlay area may carry
> `glyphs: "<1-12 hex digits>"` (`views.GLYPH_ADDRESS_RE`, `plugins/overlay._glyph_address`). `PluginView`
> draws one 20 px `<img>` per digit before the text (`pluginModel.cellGlyphs`/`glyphAssetName`/`glyphName`,
> `GLYPH_NAMES` = the community's English names), the overlay draws the PNG variant through the existing
> `recipes.IconCache` (`model.glyph_icon_names`, `GLYPH_ICON` 21 px). The text is always kept beside the
> symbols: it is what the player copies and the fallback when an image fails. `ICON_NAME_RE` now takes
> `.png|.svg` and the asset route picks the media type from the suffix (`ASSET_TYPES`); an SVG is only ever
> loaded inside an `<img>`, where script inside it does not run. The artwork itself is the NMS plugin's
> (`nms_connector/glyph_art.py`, stroke-only paths in a 0..100 box, `GLYPH_ART_VERSION` in every file name;
> `glyph_raster.py` rasterises it with Pillow because Tk cannot display SVG).

- [ ] **Step 2: Update the user manual**

In the No Man's Sky chapter of `frontend/src/manual/USER_MANUAL.md`, add to the section that describes the
plugin page:

> Portal addresses are shown as the game's own symbols as well as the twelve hex digits, so you can type them
> into a portal without translating them first. Hovering a symbol names it.

and a troubleshooting entry:

> **A portal address shows only as hex digits.** The glyph pictures are generated into the plugin's data folder
> the first time the plugin starts. Restart the backend; if they are still missing, the plugin's log line
> *glyph assets could not be written* names the folder it could not write to.

Check the wording against the actual JSX labels before committing, keep the headings unique, and run:

Run: `cd /d J:\40k-assistant && venv\Scripts\python.exe -m pytest tests/test_user_manual.py -v`
Expected: PASS

- [ ] **Step 3: Describe the feature for users**

Add the user-facing description to `J:\40k-assistant\features.md` and to the plugin's `features.md` and
`HELP.md`.

- [ ] **Step 4: State where the artwork comes from**

In `nms_connector/credits.py`, add an entry saying the glyph artwork is this project's own, drawn after the
game's symbols, and that no game or fan-site glyph files are shipped or downloaded.

- [ ] **Step 5: Bump the versions**

- App: `3.20.0` (additive contract) in `src/main.py`
- Plugin: the next `0.15.0-beta.N` in `strategicum-plugin.json`, with `app.min_version` `3.20.0`, and a
  `CHANGELOG.md` entry

- [ ] **Step 6: Run both suites**

Run: `cd /d J:\40k-assistant && venv\Scripts\python.exe -m pytest tests -q`
Expected: PASS

Run: `cd /d J:\stc-repos\40k-assistant-nomanssky && python -m pytest tests -q`
Expected: PASS

- [ ] **Step 7: Check the code shape**

Run: `cd /d J:\40k-assistant && venv\Scripts\python.exe tools/code_shape.py`
Expected: PASS — `_draw_timers_and_lines` gained a parameter and a block, so if it is in
`code_shape_baseline.json` it must come out no longer than it went in; extract the glyph row into its own
`_draw_glyph_row` method if it does not.

- [ ] **Step 8: Commit in both repos**

```bash
cd /d J:\40k-assistant
git add docs/architecture/plugins.md frontend/src/manual/USER_MANUAL.md features.md src/main.py
git commit -m "docs(plugins): portal glyphs in the page and the overlay (3.20.0)"

cd /d J:\stc-repos\40k-assistant-nomanssky
git add credits.py CHANGELOG.md HELP.md features.md strategicum-plugin.json nms_connector/credits.py
git commit -m "docs(glyphs): the glyph artwork and what it is"
```

---

## Notes for the implementer

- **Never release.** Commit locally only. Tagging, pushing and the registry pin happen when the user says so.
- **The app runs the installed plugin copy**, not the repository. Nothing picks up a plugin change until
  `tools/sync_plugin.py` has run and the backend has been restarted.
- **`GLYPH_ART_VERSION` lives in three places** by design: `nms_connector/glyph_art.py` (the source),
  `pluginModel.js` and `src/overlay/model.py` (the two hosts that build file names). Task 10 Step 5 bumps all
  three together; `tests/test_glyph_call_sites.py` does not catch a mismatch, the running app does.
- **Windows:** invoke the app's interpreter by full path (`venv\Scripts\python.exe`); bare `python` is 3.14.
