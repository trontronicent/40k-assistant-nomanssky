# Data transfer, economy stars, region guilds, save search

Design, 2026-10-14. Four independent parts, landing in this order: the field additions first
(stars, guilds), then the transfer that has to carry them, then the search.

Everything uses only view section types the app already has (`notice`, `kv`, `table`, `form`,
`tabs`, `text`), so `app.min_version` stays where it is and the standalone host needs no
contract change.

## Part 1 - economy tier as stars

The game shows an economy's strength as stars; the plugin showed `Average - 2 of 3`.

- `trade.wealth_stars(wealth)` -> a filled/empty star string over `WEALTH_ORDER`: Poor `★☆☆`,
  Average `★★☆`, Wealthy `★★★`. `Pirate` is a lawless marker, not a step on the scale, so it
  gets no stars (it already gets no rank from `wealth_level`).
- Shown in the **Systems tab only**: `Context.economy_summary` and the *Wealth* row of
  `economy_items` read `★★☆ Average`; `wealth_cell` keeps its `{text, sort}` shape so the
  column still sorts by rank rather than alphabetically.
- `Context.wealth_text` keeps returning words. The persona and the overlay read it, and a model
  reading star glyphs aloud is a regression, not a feature.

## Part 2 - guild envoy per region

Which guild's envoy a space station holds is **region-specific** (recorded by the community;
nearby systems share it). It is not in the game's data: a scan of every pak finds only
`guildshop` models, UI icons and textures for the three guilds (`tradeguild`, `explorerguild`,
`warriorguild`) - no table mapping anything to a guild. Memory was not searched yet.

So the user records it, and the plugin infers the rest of the region - the pattern the star
fixes already use.

- `history.PlanetHistory.guilds`: `{region_id: {"guild": <id>, "system": <key>, "at": <ts>}}`,
  region id = `",".join(galaxy.region(key))`. An **additive** key in `planet_history.json`:
  the file version stays 2, a file without it loads unchanged, and an older plugin reading a
  newer file ignores it (`load` reads named keys).
- `GUILDS` = `merchants`, `explorers`, `mercenaries`, plus `none` ("no envoy in this region").
- Action `set_region_guild {key, guild}` (untrusted: key must be a known system, guild one of
  `GUILDS`), offered as a `form` with a select in the system details.
- Shown as a *Guild envoy* row in the system details (`Merchants - recorded in this region, at
  Ulebsk`) and a *Guild* column in the visited-systems table. A system whose own record is
  missing but whose region is known is marked as inferred, as predicted economies are.
- `research/guilds.json` records the sources, the three guild ids with their in-game names, and
  the negative finding about the game files, so a later memory read starts from something.

## Part 3 - export and import of the plugin's data

Transfers accumulated data between the two hosts (the app's `plugins/.data/nomanssky` and the
standalone host's data dir), which is otherwise unreachable: 1,778 planets, 7,066 generated
system names and 429 economies here, none of it reproducible.

**Transport: file paths.** The view schema has no upload or download (and
`/plugins/{id}/assets/{name}` serves `image/png` only). Adding one would mean the app's
frontend, the views schema, the standalone page and an `app.min_version` bump for a feature
used twice a year. Export writes a zip where the user asks; import reads a path the user
types. Both hosts work today, unchanged.

**Archive.** `nms-data-<YYYY-MM-DD>.zip` (~12 MB; the data dir is 18 MB, mostly 1,015 icon
PNGs), written to the folder a form field names, default `<data_dir>/exports`.

- `manifest.json`: `format` (1), `plugin_version`, `host` (`plugin` | `standalone`),
  `game_build`, `created_at`, and the member list with sizes.
- Members: `planet_history.json`, `save_events.json`, `settings.json`, `route.json`,
  `settlement_screen.json`, `mapping.json`, `mapping_meta.json`, `gamedata/*`, `assets/*`.
- **Never** the host's own files (`.stc-data.json`, `.codex-written.json`, `codex_stamp.json`)
  or `*.bak`. They describe what *that* host wrote and would lie in the other one.

**Import** has three actions: `export_data`, `inspect_import` (reports the archive's manifest
and counts, writing nothing) and `import_data {path, mode}` with `mode` in `merge` | `replace`.

- **replace**: every member in the archive overwrites its file.
- **merge** (`transfer.py`, pure decisions over loaded JSON):
  - planets keyed as `history.planet_id` (address + name): newer `last_seen` wins, earliest
    `first_seen` kept, `previous_names` unioned, `confirmed` beats unconfirmed.
  - `economies` per system: recorded beats predicted, otherwise the newer entry.
  - `system_names`, `star_fixes`, `guilds`: fill gaps only - a local entry always wins, because
    the local host is where the user is playing.
  - `scans` and `save_events`: concatenated, sorted by time, capped as they are today.
  - `gamedata/` and `assets/`: taken as a whole only when the archive's `game_build` is newer
    than the local one, or no local cache exists. Never merged entry by entry.
  - `settings.json`, `route.json`, `settlement_screen.json`: left alone. Merging a codeword or
    a planned route has no meaning; `replace` is how you move them.

**Safety.** The archive is untrusted input: members must match the fixed name list (no absolute
paths, no `..`, no symlinks), each member and the total are size-capped, and every JSON member
is parsed before anything on disk is touched. The current data dir is zipped to
`backup-<ts>.zip` first. Writes land in a temp dir inside the data dir and are `os.replace`d
into place. Afterwards the connector reloads its state (`_reset_save_state`, `tables`,
`gamedata`, `history`) instead of asking for a restart.

Presented as a *Transfer* sub-tab of *Saves & source*: a notice explaining what moves, the
export form, the inspect/import form, and a table of what the last inspect or import did.

## Part 4 - search

**One box over the whole save** (`save_search.py`): a *Search your save* form on the Overview
tab that fans out to the indexes that already exist (`planet_search.PlanetIndex`,
`inventory_search.search`) plus small matchers for systems, discoveries, ships, bases and
settlements, all built on `planet_search.fold/terms/term_matches`. Results come back grouped by
kind, each group a table with that tab's own columns and row action, capped per group and
labelled `showing N of M`. The two per-tab forms stay: they are tab-local and already do the
narrow job.

**Planet search** gains ranking (most terms matched first - `planet_search.best` already
computes it, the page only used all-terms `search`), a *Matched* column naming which fields
matched, and two optional fields: biome select (from `worlds.biome_words`) and resource text.

**Inventory search** gains a *Value* column (`item value × amount`) that sorts, category terms,
and an honest `showing 500 of N` line when the cap bites.

## Testing

Each part ships with unit tests in the plugin's own suite
(`J:/40k-assistant/venv/Scripts/python.exe -m pytest tests -q`), no game and no network:

- `test_trade.py`: star strings for every scale value, `Pirate`, unknown, `None`.
- `test_guilds.py`: region grouping, inference across a region, an unknown guild id refused,
  a history file without the key, round trip through save/load.
- `test_transfer.py`: the merge decisions as pure functions (each rule above), a manifest round
  trip, and the refusals - absolute member, `..`, unknown member, oversize, damaged JSON,
  missing manifest - each asserting that nothing was written.
- `test_save_search.py`: a query hitting several kinds, group caps and the `showing N of M`
  line, an empty query, a query matching nothing.
- `test_host_contract.py` must stay green (no new section type), and `test_code_shape.py`
  bounds every new function.

Docs: the plugin's `CLAUDE.md` module table, `HELP.md` (the transfer and the search are
user-visible), `CHANGELOG.md`. The app's `USER_MANUAL.md` only needs a line if the app's own
plugin help chapter should mention the transfer.
