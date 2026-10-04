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
- **Systems** - *Current system* (live from the game, with a map), *Visited systems* (every system from your save; click one to see its map), *Planets* (every planet whose resources were read) and *Galaxy* (the galaxy map and the nearest planet with each resource).
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

## The galaxy map

*Systems → Galaxy* shows every system you know in the galaxy you are in. Drag
to move, use the mouse wheel or the zoom buttons, look **from above** or **from
the side**; **Fit** shows all your systems, **Whole map** the whole galaxy with
its centre. Click a system for its details, **Open system map** (or a
double-click) opens its star and planets.

Below the map, **Nearest planet with each resource** names, for every resource
the plugin has read, the closest planet offering it: your own system first,
then by distance. Click a row to open that system.

Distances are measured between regions (about 400 light years per step) and
are approximate: the game does not reveal where exactly a system lies in its
region, so the systems of one region are drawn on a small circle around it.
A route planner (for jumps longer than your hyperdrive allows) is planned.

## Good to know

- Items whose name the game makes up from a seed (salvaged and biological finds such as `PROC_LOOT`) keep their id.
- The gas per biome is community knowledge, not read from the game.
- Your save data (base and ship names, inventories) is shown to anyone who can open your app.
