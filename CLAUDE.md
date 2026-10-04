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
| `memory.py` | `ProcessReader` (OpenProcess QUERY_INFORMATION + VM_READ only), `scan()` over private RW regions in 16 MB chunks on `SCAN_WORKERS` (4) threads, each reading into its own reused buffer (`read_into`; `chunks()` is the one-thread path for test readers): planet records (numpy prefilter on ids + index/PlanetUA), player-state anchor (`find_aligned`, u64 at 4-aligned starts), generated system names (u64 marker search at 1 mod 8); star attributes (economy) via planet seeds (u64 search, name-cache regions first). ~1.2-2 s for 5 GB (was ~32 s). Never go back to per-chunk allocations or `bytes.find` (9 s for the anchor alone). Timing live: the first seconds of a run are on a performance core, later ones ~2.5x slower on an efficiency core (i9-14900K) - compare steady-state rounds |
| `live.py` | `LiveMemory`: pacing of scans, current system (player state or majority of planet records + slot watching), economies and names after a scan |
| `timers.py` | settlement constructions (`SettlementStatesV2`: slot `NextBuildingUpgradeIndex`, start `LastBuildingUpgradesTimestamps[slot]`, duration `GcSettlementGlobals.SettlementBuildingTimes[class]` at 0x99B0) and frigate expeditions (`StartTime` + events x `GcFleetGlobals.TimeTakenForExpeditionEvent` 0x1364, easy 0x1368) - libMBIN offsets + 0x20 header, sanity-checked, `FALLBACK` = values measured 2026-10-04; `timers_section` sends a `timers` section when `ctx.section_types` has it (app 3.8.0), else a table |
| `equipment.py` | *Inventory → Equipment*: Technology slots of `Inventory_TechOnly`/`Inventory` (exosuit), `Multitools[i].Store` (unused entries: empty `Resource.Filename`; active = `ActiveMultioolIndex`, the save's spelling) and `FreighterInventory_TechOnly`. Icons for non-items: `gamedata.EXTRA_ICONS` (id -> texture) is used by `icon_texture`/`icon_name`/`ensure_icons` - planet hints (GcPlanetDataResourceHint = Hint 0x10 + Icon 0x10; Icon ids BONES/GRUBS/SALVAGE -> frontend `bones.dds`, HUD `pickup.grub`, `pickup.techdebris`) and the settlement screen icons `SETTLEMENT_<BASIC|POSITIVE|NEGATIVE>_<STAT>` (`textures/ui/frontend/icons/settlement/`). |
| `ships.py` | *Ships & bases*: `ShipOwnership` (type from the model folder, `Inventory.Class`, `BaseStatValues` ^SHIP_DAMAGE/SHIELD/HYPERDRIVE/AGILE in %, technology = Technology slots of `Inventory` + `Inventory_TechOnly`, `SHIPSLOT_DMG*` = damaged slots). **Warp range is not in the save**: sum of `Ship_Hyperdrive_JumpDistance` (GcStatsTypes 149) bonuses - `nms_reality_gctechnologytable` (GcTechnology ID 0x108, StatBonuses 0x158, {f32 bonus, i32 level, u32 stat}; HYPERDRIVE 100, *_SPEC/*_ROBO 600) and procedural `nms_reality_gcproceduraltechnologytable` (ID 0x40, StatLevels 0x50, {u32 stat, f32 max, f32 min}, 0x14; UP_HYP4 220-265: the exact value is seeded) - times (1 + ship hyperdrive %); adjacency/supercharge ignored, so an estimate (low-high). Validated: HYPERDRIVE must be 100 ly. HDRIVEBOOST1-4 = red/green/blue/purple stars, no range. The route form's default range = primary ship's low estimate. Freighter: `Freighter_Hyperdrive_JumpDistance` (171) from the same tables (F_HYPERDRIVE 100, F_HDRIVEBOOST1-3 200/300/800, F_HACCESS* 50, UP_FRHYP*), technology in `FreighterInventory_TechOnly`. Routes drop stops whose recorded star colour (`economies[..].star`) the primary ship cannot reach. |
| `settlements.py` | the *Settlements* tab: your `SettlementStatesV2` entries (`Stats` int[8] by GcSettlementStatType, `Population`, `ProductionState`, `Perks` `^ID#seed`, `PendingJudgementType`, `LastJudgementTime`); `GcSettlementGlobals` StatsMax/Min 0xB3D0/0xB3F0, Bad/Good thresholds 0xB370/0xB390, JudgementWaitTimeMax/Min 0xB430 (7200/900 s: the next decision is only a window, the game draws the wait), MaxNPCPopulation 0xB440; `settlementperkstable.mbin` records 0x78 (desc 0x00, name 0x20, id 0x50, StatChanges 0x60, flags 0x70). Perk strength = better/worse for the player, not up/down. Stored stats are not the screen's values (population capacity is stored 0): `LiveSettlements` reads the computed ones from memory - seed u64 (8-aligned), ints (1, 0), then int[8] (the seed is in memory ~150 times: a first 'seed twice' anchor was a coincidence, and a look-alike [41,41,41,41,50,39,39,39] with ints (36, 46) passed range checks alone - the marker ints are required) (verified against the screen 2026-10-04: [52, 41, 489454, 395010, 0, 908027, 358, 552] = 20/52, 34 %, 489,454/day, 395,010/day, alert 36 %); the record exists only while the settlement's screen is open (absent on its planet with the screen closed), so the search (~0.75-1.5 s) runs every 15 s only for settlements in your current system, known records are re-read (48 bytes) every tick, and the last reading is kept in `settlement_screen.json`. Procedural perk names (`%PROD_ADJ% %PROD%`) are seeded: shown by description. The next-decision countdown the game shows was searched in memory on 2026-10-04: no end time stored next to the live record |
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
