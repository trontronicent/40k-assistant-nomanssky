# Changelog

## Unreleased

- **Ships**: *Ships & bases* lists every ship with type, class, its own bonuses,
  slots (and damaged ones), an **estimated warp range** (hyperdrive 100 ly plus
  upgrades - e.g. an S-class upgrade 220-265 ly - and the ship's hyperdrive bonus,
  from the game's technology tables) and the star colours it can reach; the
  primary ship's technology with charge and what each part adds. The route
  planner's jump range starts with the primary ship's estimate.
- **Galaxy map**: shows the systems around you that the game's galaxy map knows
  (small grey points), can colour systems by economy or conflict level, and
  draws the planned route. Those systems are also stops for the route planner.
- **Texts and icons**: planet hints (*Ancient Bones*, *Salvageable Scrap*, *Vile
  Brood Detected*) were shown as keys (`UI_BONES_HINT`); the current mission is
  shown with the game's description instead of its id; items in the storage
  containers had no icons.
- **Settlements tab**: the economy of each settlement you run - population,
  the stored stats (productivity, happiness, maintenance, debt, sentinel alert,
  bug attacks, ...) with the game's own range for each, production (what is
  ready, how much it holds), perks with their names, kind and which stats they
  make better or worse, and the window in which the next decision comes (the
  game waits 15 min to 2 h). Ranges, the wait and the perk table come from the
  game's files. The stats appear as the settlement screen shows them (20 / 52,
  34 %, 489,454 units/day): the game computes them from buildings and perks and
  keeps them in memory while you are at the settlement, where the plugin reads
  them (and remembers the last reading); the save's stored values differ.
- The timers no longer claim the game saves about once a minute: it saves when
  you leave your ship, warp or use a save point, and a new construction shows
  after that save.
- **Timers**: the *Overview* tab shows when the building under construction in
  each of your settlements is finished (e.g. *Kay City: Factory built* at 13:21)
  and when frigate expeditions return, with the next expedition event. Start
  times come from the save, durations from the game's own files. With the 40k
  Assistant 3.8.0 they count down live and a bell per timer sends a browser
  notification when it ends - also to your phone; older apps show a table.
- **Scans stay fast while you play**: 1-2 seconds instead of 5-13. Finding your
  position in memory (the save's start addresses) took up to 9 seconds per scan
  on its own; it is now searched like the other records. The scan runs on four
  threads: on CPUs with performance and efficiency cores (such as Intel's 12th-14th
  generation) Windows moves a busy background thread to a slower core after a
  few seconds, which made scans 2.5 times slower.
- **New planets appear sooner after a warp**: with scans this cheap, the
  follow-up scan after arriving runs twice - 15 and 45 seconds after arrival
  (it used to run once, after 45 seconds).
- **Flora and fauna in English too**: some planets hold these values already
  translated into the game language ("Verloren"); they are now matched back to
  the game's text so the page shows "Lost (Verloren)" like everywhere else. A
  text with two English meanings ("Ungewöhnlich": Unusual or Uncommon) is told
  apart by the planet's other value (exotic planets use the unusual set).
- **The route follows you**: a planned route is planned again from where you
  are whenever you reach another system, so it shrinks as you fly it, and in
  the target system the page says you have arrived. Before, it kept showing the
  system you planned it in as "(you)".
- **Your planet from the last save**: while the exact position cannot be read
  from memory, *Where you are now* shows the planet of your newest save when
  that save is in the system you are in (marked *at the last save* with its
  time) instead of *unknown*.

## 0.9.1 — 2026-10-04

- **Fixed: the current system stayed on the old one after a warp.** The game
  sometimes writes your new position into a fresh copy of its player state
  while the copy the plugin followed stays frozen at the old system. A copy
  that changed now wins over one that did not, and a warp is also noticed from
  the planets in memory while a copy is followed.
- **Game scans are about 10x faster**: reading the planets, system names and
  economies from the running game takes about 2.5 seconds instead of 30 or more
  (measured on 5 GB of game memory). Memory is read into one reused buffer, and
  planet, name and star records are found with vectorised checks instead of
  parsing a million false candidates and searching memory once per planet seed.
  The economy lookup searches the galaxy map's memory first and stops as soon as
  every system is found.

## 0.9.0 — 2026-10-04

- **Categories and tooltips for items and resources**: inventory tables have a
  *Category* column (the subtitle the game shows under an item's name, English
  and game language), and hovering an item's name shows its category and the
  game's description. Planet resources get the same tooltip.
- **Trade goods** say in their tooltip which economies pay well for them (with
  the price factor), the nearest system of such an economy you know (or that you
  have not found one yet), and where they are cheap to buy.
- **Storage tab**: storage containers 0-9 (numbered as in the game; renamed
  containers show their name), other storages that hold something, and which
  containers are empty. Freighter cargo now counts as freighter inventory.
- The item cache is rebuilt once (new fields); icons are converted again.
- Needs the 40k Assistant 3.7.0 (tooltips on table cells).

## 0.8.1 — 2026-10-04

- **Generated system names**: systems nobody renamed show the name the game made
  up for them (e.g. *Ulebsk*) instead of *System <portal address>*. Read from the
  galaxy map's name cache in the game's memory (the systems around you) and kept
  in the history; a renamed system shows its original name under *Where you are*.

## 0.8.0 — 2026-10-04

- **Route planner** (*Systems → Route*): target system (known, or any portal
  address) and jump range; the route with the fewest jumps, using your known
  systems as stops where they cost no extra jump and naming the regions to aim
  for through unknown space; listed leg by leg and drawn on a map.
- The route planner is marked as **very much work in progress** (plugin description,
  Route tab, help): distances are estimated from regions and routes are not tested
  in the game yet.
- The help names the author (Reto Kummer alias Reat Kay) at the top.
- Needs the 40k Assistant 3.6.0 (forms and map lines in plugin views).

## 0.7.0 — 2026-10-04

- **Economy per system:** economy, wealth, conflict and dominant race, read from
  the game's galaxy map data (found through the seeds of the system's planets)
  while you are there; kept in the planet history.
- **Trade goods:** the game's trading table says what each economy sells cheaply
  and what it pays well for; system maps list the five trade goods of each, the
  visited-systems table shows economy and conflict.
- **Systems → Trade:** the economies of your systems and trade routes - for every
  kind of goods, the nearest system to buy it and the nearest to sell it.

## 0.6.0 — 2026-10-04

- **Galaxy map** (*Systems → Galaxy*): every known system of your galaxy on a map
  you can drag, zoom and look at from above or the side; click a system for its
  details and open its system map. Your system, your bases and systems with
  recorded resources are coloured.
- **Nearest planet with each resource:** for every resource read so far, the
  closest planet offering it (your own system first, then by distance).
- Needs the 40k Assistant 3.5.0 (starmap views).

## 0.5.0 — 2026-10-04

- **Help and credits in the app's manual:** the plugin's help (`HELP.md`) and its
  credits appear in the 40k Assistant's manual under *Plugin Help*; the plugin
  list links to it.
- Author: Reto Kummer alias Reat Kay.
- Needs the 40k Assistant 3.4.0 (manifest keys `help` and `credits`).

## 0.4.1 — 2026-10-04

- Shorter plugin description: 0.4.0's exceeded the registry's 300-character
  limit, so 0.4.0 was never published. Otherwise identical to 0.4.0.

## 0.4.0 — 2026-10-03

- **Tabs:** the page is split into *Overview*, *Systems* (sub-tabs *Current
  system*, *Visited systems*, *Planets*), *Inventory* (sub-tabs per exosuit,
  starship and freighter), *Ships & bases* and *Saves & source*.
- **Gas:** every planet shows the gas an atmosphere harvester collects there
  (sulphurine on scorched, barren and volcanic worlds, radon on irradiated and
  frozen ones, nitrogen on lush and toxic ones, oxygen on exotic ones), with
  its icon. Planets recorded by earlier versions get it too.
- **System map:** click a visited system to see it as a small solar system:
  the star with what is known about the system (portal address, region, system
  index, who named it, when it was discovered, your bases there, black hole /
  Atlas / purple-star systems) and its planets, coloured by biome and sized by
  class; click a planet for its resources, gas, weather, flora, fauna,
  sentinels and your discoveries. Planets known only from the save (uploaded
  names, discoveries) appear as *not scanned yet*. The current system has its
  own map.
- Tables use the full width and no longer break words in the middle.
- **Planets of earlier systems are kept:** after a warp the game can reuse a
  planet slot while the record still carries the previous planet's address,
  so the new system's planets replaced the old system's in the history. The
  history now merges each scan differentially - planets are identified by
  address *and* name, never replaced by a different planet, and a planet whose
  address belongs to another planet is filed under the system you are in;
  a planet first filed by a stale address is moved once it is read in its own
  system. The previous file is kept as `planet_history.json.bak` (read if the
  main file is damaged); 0.3.0 histories are migrated.
- When the game holds several copies of the player state, the plugin follows
  the copy that changes when you travel.
- **Where you are, also without a save:** the game keeps the player state readable only around saves
  and loads (after a game restart it was not found at all). The plugin now tells the current system
  from the planets the game has loaded, notices a warp by re-reading the planet slots (8 bytes per
  planet, no full scan) and no longer trusts a player-state copy whose memory was reused. The planet
  you are on shows as *unknown* until the next save.
- **Renamed planets are not duplicated:** planets carry their generation seed; the same planet
  under a new name (renamed, or an uploaded name arrived) takes over its entry and keeps its first
  sighting and old name.
- *Saves & source* lists the last 50 memory scans: where you were, how many
  planets were read (by system), what was new, and what was re-filed.
- Needs the 40k Assistant 3.3.0 (tabs, clickable rows and maps in plugin views).

## 0.3.0 — 2026-10-03

- **Live data from the running game (read-only):** while No Man's Sky runs,
  the plugin reads the planets of the system you are in from the game's
  memory - name, type, weather, the three resources and plant resource, flora,
  fauna and sentinels (for your combat setting) - and remembers every planet
  it sees (`planet_history.json`). It also knows which system and planet you
  are on right now.
- **Visited systems:** every system in the save's visit list and discoveries,
  with uploaded system and planet names, plus the recorded planets with their
  resources.
- New permission `read-game-memory`; needs the 40k Assistant 3.2.0.

## 0.2.0 — 2026-10-03

- Inventories show each item's name in English and in the language the game
  runs in (Steam's language setting), plus the game's own icon. Names and
  icons are read from the installed game's files (`GAMEDATA/PCBANKS/*.pak`),
  cached per game build, and re-read automatically after a game update
  (*Re-read item names* does it on demand).
- Needs the 40k Assistant 3.1.0 (icon cells in plugin views, the `zstandard`
  package for the game's archives).

## 0.1.0 — 2026-10-03

- First version: save-file connector (status, location with portal address,
  inventories, ships, bases, fleet) and a log of every save write.
