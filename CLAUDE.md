# CLAUDE.md - No Man's Sky plugin (`nomanssky`)

A backend plugin ("STC") for the 40k Assistant (`J:\40k-assistant`). It reads No Man's Sky save files, the
installed game's files and - read-only - the running game's memory, and returns a declarative view (no
JavaScript). The app side (loader, view schema, permissions, trust) is documented in
`J:\40k-assistant\docs\architecture\plugins.md`; read it only when you change what a view may contain or need an
app feature (then the app version and `app.min_version` here go up together).

## Commands

```bash
J:/40k-assistant/venv/Scripts/python.exe -m pytest tests -q     # ~90 tests, < 1 s, no game needed
```

Plugin work runs **only these tests**; the app's suite only when the app changed. Tests never touch a running game
(`tests/conftest.py` patches `memory.find_game_pid`); fixtures build fake saves, paks, MBIN tables and memory.
Live checks against the real game/save are scratchpad scripts that import `nms_connector` (read-only: never write
into `J:\40k-assistant\plugins\.data\nomanssky`, the installed plugin's data, unless asked).

## Module map (`nms_connector/`)

| Module | Role |
|---|---|
| `plugin.py` | `NmsConnector`: start/stop, 5 s tick, `view()` (tabs Overview / Systems / Inventory / Ships & bases / Saves & source), `action()` (rescan, update_mapping, scan_memory, rebuild_names, clear_history, open_system, plan_route), inventory + storage tables |
| `saves.py`, `lz4.py`, `watcher.py` | find/decode `save*.hg` (chunked LZ4, obfuscated JSON keys -> MBINCompiler `mapping.json`, downloaded), save-write log |
| `summary.py` | save -> snapshot (currencies, location, inventories, `storage` = Chest1..10 = game containers 0-9, ships, bases) and address helpers (`unpack_address`, `address_portal`, `system_key_of`) |
| `game_install.py`, `hgpak.py`, `mbin.py`, `gamedata.py` | Steam install + language; HGPAK v2 reader; MBIN tables with self-calibrated offsets (id, name keys, icon, `*_SUB` category key, `*_DESC` description key); item DB cached in `gamedata/items.json` (`CACHE_FORMAT`, bump when fields change), icons -> PNG in `assets/`, trading table |
| `memory.py` | `ProcessReader` (OpenProcess QUERY_INFORMATION + VM_READ only), `scan()` over private RW regions in 64 MB chunks: planet records, player-state anchor, generated system names; star attributes (economy) via planet seeds |
| `live.py` | `LiveMemory`: pacing of scans, current system (player state or majority of planet records + slot watching), economies and names after a scan |
| `history.py` | `PlanetHistory` (`planet_history.json`: planets keyed address+name, renames by seed, scans log, `economies`, `system_names`), `visits_from_save` |
| `planets_view.py` | `Texts` (names, categories, tooltips), `Context` (`visit()`, economies, trade hints), all system/planet/galaxy/trade/route sections |
| `galaxy.py`, `trade.py`, `route.py` | region distances (~400 ly per voxel step, confirmed against the in-game core distance), economies/trade goods (`TRA_<CAT><n>`), route planner (Dijkstra by jumps) |

## Memory layouts (libMBIN 7.04 = in-memory layout; verified 2026-10-03/04)

- `GcPlanetData` (0x3AD2): substance ids at 0x33D0 / 0x3400 / 0x3430, index 0x353C, name 0x3A4E, `PlanetUA` 0x3368
  (planet nibble = index + 1), seed 0x3180 + 0xA0.
- `GcGalaxyStarAttributesData` (0x6AC): PlanetSeeds 0x400, TradingData 0x680, conflict/planets/race/star 0x688+.
  Found by the seeds of known planets.
- Player `UniverseAddress`: save's GameStartAddress1/2 + 0x90 - only present around saves/loads.
- Generated system names: 0x218-byte records, name at +0 (pre-filled `" ! NO PROC NAME !"`, so `PROC NAME !` sits at
  +0x0D after short names), packed address at **+0x20C after the name** (the address 0xC *before* a name belongs to
  the previous record). Walk the array by the stride from each marker.
- Packed address: X bits 0-11, Z 12-23, Y 24-31, galaxy 32-39, system 40-51, planet 52-55.

## Rules

- Read-only towards the game and the save folder, always.
- Manifest `description` <= 300 characters (a test checks it); bump `version` + CHANGELOG for every release; the
  release recipe is in the app's `CLAUDE.md` ("Plugin release recipe"). Push/tag only when the user says so.
- Every user-visible change updates `HELP.md` (shown in the app manual's *Plugin Help*), `CHANGELOG.md`, and the No
  Man's Sky section of `J:\40k-assistant\frontend\src\manual\USER_MANUAL.md`.
- Test functions carry a docstring (what, expected, why). Form values and action params are untrusted input.
- Files here are CRLF: edit with the Edit tool or a Python script that normalises line endings.
