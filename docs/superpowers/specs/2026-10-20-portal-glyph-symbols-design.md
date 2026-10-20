# Portal glyph symbols in the page and the overlay

**Date:** 2026-10-20
**Status:** approved design, not yet implemented
**Repos:** `40k-assistant-nomanssky` (artwork, emitters, view wiring) and `40k-assistant` (one additive view/overlay
contract plus the asset route)

## Why

A portal address is shown today as twelve hex digits (`006202925E80`). The player types *symbols* into a portal, so
the hex is a translation step they have to do in their head. The chat answer already names the glyphs
(`craftable.glyph_names`, the community's English names), but nothing anywhere shows the shapes.

This change draws the twelve symbols next to every address, in the app's plugin page and in the desktop overlay.

## Decisions taken before the design

- **The artwork is our own.** The ready-made PNGs on fan sites are Hello Games' glyph art. Rather than redistribute
  or runtime-download them, the sixteen glyphs are hand-authored as vector outlines in this repo. They are
  recognisable as the game's glyphs without being its files, and being stroke-only they can take the UI's own
  colour instead of the game's glow.
- **The feature lives in the plugin.** Everything except one additive contract shape and the asset route is plugin
  code: the artwork, the rasteriser, the digit mapping, and every call site.
- **Both delivery formats are needed.** The page is a browser and gets SVG; the overlay is Tk, which cannot display
  SVG, and gets PNG. Neither the app venv nor this repo's vendored runtime has an SVG rasteriser (`cairosvg`,
  `svglib`, `skia`, `aggdraw` all absent; Pillow only), so the PNGs are rasterised from the same source by Pillow.

## Architecture

### 1. `nms_connector/glyph_art.py` — the single source of truth

A module-level table of sixteen entries, indexed by the value of the hex digit, so it lines up with the existing
`craftable.GLYPHS` names (`0` Sunset … `F` Atlas) with no second ordering to keep in step.

Each entry is a list of subpaths in a `0..100` box. A subpath is a list of segments using only `M`, `L`, `C` and
`Z` — a command set small enough that the flattener below stays trivial, and wide enough for the organic shapes
(Bird, Diplo, Fish, Boat, Sunset) as well as the geometric ones (Voxel, Atlas, Tent, Rocket, Tree).

Shapes are **stroke-only**: no fills, round caps and joins, one stroke width across the set. The glyphs read at
small sizes, theme with `currentColor` in the browser, and stay a single colour in Tk.

`GLYPH_ART_VERSION` is a module constant. It is part of every generated file name, so editing a shape invalidates
the generated assets without any cache-busting logic.

Public functions:

| Function | Returns |
|---|---|
| `glyph_index(digit)` | `0..15` for one hex digit, `None` otherwise |
| `glyph_svg(index)` | the entry as an `<svg viewBox="0 0 100 100">` string, `stroke="currentColor"`, no fill |
| `glyph_png(index, size)` | a Pillow `Image`, transparent background, white strokes |
| `glyph_asset_names(index)` | `("glyph-<v>-<d>.svg", "glyph-<v>-<d>.png")` — the names both hosts reference |

`glyph_png` flattens each cubic segment to a polyline with a small de Casteljau helper (Pillow has no bezier
primitive), draws at 4× the requested size and downsamples with `Image.LANCZOS`, which is how the strokes come out
smooth without an anti-aliasing library.

### 2. `nms_connector/glyphs.py` — addresses to glyphs

Thin and pure, so the call sites stay one-liners:

- `glyph_digits(address)` → `None` for anything that is not 1–12 hex digits (never raises, never half-renders),
  else the list of glyph indices.
- `ensure_glyph_assets(assets_dir)` → writes the sixteen `.svg` and sixteen `.png` files for the current
  `GLYPH_ART_VERSION` if they are not already there, and removes files of an older version. Called once from the
  connector's start, the same way `_ensure_icons` already works.

### 3. App contract — the `glyphs` key

One additive shape, in `src/plugins/views.py`:

- `GLYPH_ADDRESS_RE = re.compile(r"^[0-9A-Fa-f]{1,12}$")`.
- `_table_cell` keeps `glyphs` when it matches, exactly as it already keeps `icon`, `hint` and `sort`. A cell with
  only `glyphs` and no other extra key still becomes a dict, since the glyphs are the content.
- `_labelled` (which serves both `kv` and `stats`) keeps `glyphs` on an item the same way, so *Where you are* and
  the system-map star can carry one.

A cell or item therefore reads `{"text": "006202925E80", "glyphs": "006202925E80"}`. The text is kept beside the
symbols on purpose: it is what the player copies, searches and pastes, and it is what a screen reader should get
if the images fail.

`ICON_NAME_RE` is widened to `\.(png|svg)$`, and `manager.asset_path` serves `.svg` as `image/svg+xml` with the
`nosniff` and `max-age` headers it already sends. The files are only ever loaded inside an `<img>`, where script
inside an SVG does not execute; the route keeps refusing separators and `..` unchanged.

`PluginView` renders a `glyphs` value as a row of `<img>` elements before the text, each about 20 px, `alt` set to
the glyph's English name so the row reads as names when images are off, and the whole row carrying the address as
its tooltip.

### 4. The overlay

An overlay area may carry `glyphs` next to its `lines`; `plugins/overlay.normalize_overlay` checks it with the
same `GLYPH_ADDRESS_RE`. The overlay process draws the PNG variant through the `PhotoImage` path that already
exists for recipe item icons — built on the Tk thread, cached per file, and an area without its images is still a
correct area.

### 5. Call sites in the plugin

Every place an address is rendered today gains the key, and nothing else changes:

- `planets_view.where_you_are` — *Portal address*
- `planets_view.system_map` star — *Portal address*
- `planets_view` visited-systems table — the portal column
- `planets_view` route form result — the target's address
- orbit body sublabels that are an address
- `companion.overlay()` location area

Chat text is deliberately untouched: a model reads the glyph *names* aloud, and `companion.glyph_lines` already
gives it those.

## Error handling

Nothing about this feature may cost the player a view. Each layer degrades to the layer below:

- A malformed or absent address → `glyph_digits` returns `None` → the key is simply not set → the plain hex shows,
  exactly as today.
- An asset that failed to write → the app drops the key at normalisation or the `<img>` fails → text alone.
- A rasteriser failure → logged at warning (the overlay loses its symbols, which has a visible consequence) and
  the SVG side is unaffected.

## Testing

**Plugin:**

- every one of the sixteen entries parses, and `glyph_svg` emits well-formed SVG with a `viewBox` and no `fill`
- `glyph_png` yields a transparent image with ink in it, and the sixteen images are pairwise distinct (guards
  against a copy-paste entry)
- both emitters are deterministic for the same input
- `glyph_digits` accepts 1–12 hex digits in either case and rejects empty, 13 digits, `0x` prefixes and non-hex
- `ensure_glyph_assets` writes 32 files, is idempotent, and clears files of a superseded `GLYPH_ART_VERSION`
- the call sites set `glyphs` alongside the unchanged text

**App:**

- `normalize_view` keeps a valid `glyphs` on a table cell and on a `kv` item, and drops an invalid one while
  keeping the text
- `normalize_overlay` does the same for an area
- SSR of a cell and an item with `glyphs`
- the asset route serves `.svg` with `image/svg+xml`, still refuses traversal, and still refuses an unknown
  extension

## Documentation

- `docs/architecture/plugins.md`: the `glyphs` key on cells, `kv`/`stats` items and overlay areas; the widened
  asset route.
- `frontend/src/manual/USER_MANUAL.md`: the No Man's Sky chapter gains a line that portal addresses are shown as
  the game's symbols, and a troubleshooting entry for an address that shows as hex alone.
- plugin `features.md`, `CHANGELOG.md`, `HELP.md`.
- `credits.py`: the glyph artwork is this project's own, drawn after the game's symbols — stated so no one assumes
  it was lifted.

## Versions

App minor bump (additive contract); the plugin's `strategicum-plugin.json` takes `app.min_version` of that app
version and keeps the `0.15.0-beta.N` line.
