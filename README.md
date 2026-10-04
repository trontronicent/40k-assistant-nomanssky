# No Man's Sky connector for the 40k Assistant

A plugin (STC) for the [40k Assistant / Strategicum](https://github.com/trontronicent/40k-assistant).
It reads your **No Man's Sky save files** and shows what a companion needs to
know. Install it from the app's **Plugins → Manage plugins** page.

Author: **Reto Kummer alias Reat Kay**. The plugin's help (`HELP.md`) and
credits appear in the 40k Assistant's manual under *Plugin Help* (app 3.4.0+).

## What it shows

- **Status:** units, nanites, quicksilver, health, shield, ship health, play time
- **Location at the last save:** galaxy, portal address (12 hex glyphs), region,
  system and planet index, your bases in that system
- **Inventories:** exosuit, primary starship, freighter, with each item's name in
  English and in the game's language (e.g. *Sodium* / *Natrium*), its official
  icon and its id (`CATALYST1`)
- **Ships, bases, frigates, expeditions, companions, current mission id**
- **Current system (live):** while the game runs, the planets of the system you
  are in - name (and the uploaded name), type, weather, three resources, plant
  resource, the gas an atmosphere harvester collects, flora, fauna, sentinels -
  and which planet you are on
- **Galaxy map:** every known system on a map you can pan and zoom, and the
  nearest planet with each resource
- **Economy and trade:** economy, wealth, conflict and race per system, what is
  cheap to buy and what sells well there, and trade routes between your systems
- **Route planner** (very much work in progress): the fewest-jumps route to a known
  system or a portal address for your jump range
- **Visited systems and planets:** every system you visited (from the save,
  with uploaded names) and every planet the plugin has seen, with its resources.
  Click a system for its **map**: the star with the system's facts and its
  planets by biome and size; click a planet for its details
- Everything is grouped into tabs: *Overview*, *Systems* (*Current system*,
  *Visited systems*, *Planets*), *Inventory* (*Exosuit*, *Starship*,
  *Freighter*, *Storage*), *Ships & bases*, *Saves & source*
- **Item categories and tooltips:** category column, the game's description on
  hover, and for trade goods where they sell and whether you know such a system
- **How often the game saves:** every save write the connector sees, with the
  time since the previous one

The data is as fresh as the last save the game wrote. Live data (position while
flying, events) would need a game mod and is a possible later addition.

## How it works

- Looks for saves in `%APPDATA%\HelloGames\NMS\<account>\` on Windows, or in the
  Steam Proton prefix on Linux. Set `NMS_SAVE_DIR` to use another folder.
- Checks the folder every 5 seconds. A new save is read once it has not changed
  for 2 seconds, so a file is never read while the game is writing it.
- **Read-only:** it never writes into the game's folders. Its own data (the save
  history and the key mapping) lives in the app's `plugins/.data/nomanssky/`.
- Save files are LZ4-compressed JSON with obfuscated keys. The key names come
  from `mapping.json`, which the plugin downloads from the latest
  [MBINCompiler](https://github.com/monkeyman192/MBINCompiler) release
  (LGPL-3.0, not redistributed here) on first start and again after a game
  update makes keys unknown (*Update key mapping* does it on demand).
- **Item names and icons** come from the installed game itself: the item tables,
  the language files and the icon textures inside `GAMEDATA/PCBANKS/*.pak`
  (HGPAK archives, zstd-compressed). The game folder is found through Steam's
  library list (`NMS_GAME_DIR` overrides it), the language is the one Steam
  starts the game in (`NMS_LANGUAGE` overrides it). The names are cached per
  game build in `plugins/.data/nomanssky/gamedata/`; icons are converted to
  64 px PNGs in `assets/` when an item first appears in a save. The game's
  assets stay on your computer; nothing is uploaded or redistributed.
- **Live data** comes from the running game's memory, read-only: the process
  is opened with *query* and *read* rights only (no write, no injection; the
  game has no anti-cheat). Planets are found by their data (`GcPlanetData`
  records in MBINCompiler's layout, validated by name, index and the planet's
  packed address). Your exact position comes from the player state (found via
  the save's fixed start addresses), which the game keeps readable only around
  saves and loads; otherwise the current system is judged from the planets the
  game has loaded, and the planet you are on shows as unknown. A scan reads
  ~5 GB in ~2-3 s (the economy lookup for a new system adds well under a
  second), so it runs when the game starts, when you arrive in another
  system (and once more 45 s later, when the other planets have been
  generated), and every 5 minutes; in between only your address (or the
  addresses in the loaded planet slots) is re-read. Windows only.
- Planet resources are not in the save (the game generates them from the
  seed), so systems you visited before installing 0.3.0 show names and
  discovery counts, but resources only once you return.
- Recorded planets are kept in `planet_history.json` (previous version in
  `.json.bak`) and only ever added to: each scan is merged differentially, a
  planet is identified by its address and name, and a record whose address
  already belongs to another planet (the game reuses planet slots after a
  warp) is filed under the system you are in. *Saves & source* logs the last
  50 scans.
- The atmosphere gas is not stored on the planet either: the game picks it by
  biome (sulphurine: scorched, barren, volcanic; radon: irradiated, frozen;
  nitrogen: lush, toxic; oxygen: exotic). Dead worlds have none; water worlds
  and gas giants are left blank rather than guessed.
- Items whose name the game generates from a seed (salvaged and biological
  finds such as `PROC_LOOT#01474`) keep their id: the tables hold no fixed name
  for them.

## Permissions

`read-game-files` (the save folder and the game's data files), `read-game-memory`
(the running game's memory, read-only) and `network` (downloading `mapping.json`
from GitHub). Like every code plugin it runs inside the 40k Assistant backend,
which is why the app asks you to confirm that you trust it before installing.

No Man's Sky has no anti-cheat, and the plugin does not touch the game process.

## Privacy

Save data (base names, ship names, inventories) is shown on the app's plugin
page. Anyone who can reach your 40k Assistant (LAN, tunnel) can read it there.

## Development

Python 3.11+. Besides the standard library it uses what the 40k Assistant
provides: `zstandard` (the game's archives; Python 3.14's `compression.zstd`
works too), Pillow (icons), numpy and psutil (memory reading). Without them names and icons are reported as
unavailable; saves are still read.

```
python -m pytest tests
```

## License

MIT, see [LICENSE](LICENSE).
