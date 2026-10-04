# No Man's Sky

A companion for No Man's Sky: it reads your save files and - while the game
runs - the game's memory, and shows what you have, where you are and every
system you visited. It only reads: nothing in the game or its folders is ever
changed, and the game process is never modified.

## The page

Open it from **Plugins → No Man's Sky** in the header. The buttons at the top:

- **Rescan** - read the newest save file again now.
- **Scan game now** - read the planets of the current system from the running game now (takes about 10 seconds).
- **Update key mapping** - download the newest key list after a game update (when the page reports unknown keys).
- **Re-read item names** - read item names and icons from the game files again, for example after changing the game's language in Steam.
- **Clear save history** - forget the recorded save writes.

The tabs:

- **Overview** - units, nanites, quicksilver, health, where you were at the last save, where you are now, your fleet and companions.
- **Systems** - *Current system* (live from the game, with a map), *Visited systems* (every system from your save; click one to see its map) and *Planets* (every planet whose resources were read).
- **Inventory** - exosuit, starship and freighter, each item with its icon and its name in English and in the game's language.
- **Ships & bases** - your ships and bases with portal addresses.
- **Saves & source** - how often the game saves, the recent save writes, where the data comes from and the last memory scans.

## Live data

While No Man's Sky runs, the plugin reads the planets of the system you are
in: name (and the name someone uploaded), type, weather, three resources, the
plant resource, the gas an atmosphere harvester collects, flora, fauna and
sentinels. Every planet it sees is remembered, so the *Planets* tab grows as you
travel. Planet resources are not stored in the save, so systems you visited
before using the plugin show their names, but no resources until you go back.

Your exact position (the planet you are on) can only be read around saves and
loads; the rest of the time the plugin tells your system from the planets the
game has loaded, and the planet shows as *unknown*. Save in the game and press
**Scan game now** to get it.

Live data needs Windows. If the game runs as administrator, the app must too.

## The system map

A system map shows the star (portal address, region, system index, who named
it, when it was discovered, your bases there, and whether it is a black hole,
Atlas or purple-star system) and its planets, coloured by biome and sized by
class. Click a planet for its resources, gas, weather, flora, fauna, sentinels
and your discoveries there. Planets known only from your save appear as *not
scanned yet*.

## Good to know

- Items whose name the game makes up from a seed (salvaged and biological finds such as `PROC_LOOT`) keep their id.
- The gas per biome is community knowledge, not read from the game.
- Your save data (base and ship names, inventories) is shown to anyone who can open your app.
