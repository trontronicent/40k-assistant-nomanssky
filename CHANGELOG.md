# Changelog

## Unreleased

- **Planet search**: *Systems → Planets* has a search field - find recorded planets
  by what they are like (type, weather, resources, plants, gas, flora, fauna,
  sentinels, name) in English or the game's language: *sengend heiß* finds the
  "Sengend heißer Planet"s, *heiss* also finds *heißer*, umlauts and ß need not be
  typed exactly. Results are nearest first and open the system map. The persona
  answers planet questions the same way ("Wo gibt es sengend heiße Planeten?").

## 0.10.0 — 2026-10-05

- **Trade goods by kind and their value**: the item database now holds each
  product's base value from the game (trade goods 1,000 / 6,000 / 15,000 / 30,000
  / 50,000 units by tier), shown in the tooltip. The persona groups trade goods by
  kind for the inventory you ask about - "what kind of trade goods do I have the
  most aboard my ship?" now gets e.g. *Technology: 233 units, base value 3,596,000,
  about 5.0-6.5 million where needed, nearest buyer Zeta Sol* instead of the
  largest single stack. A cargo question no longer pulls in the ship's technology.

- **Star positions (prototype)**: exact distances from the galaxy map. Lock a star
  on the map twice from different directions: where the two lines of sight cross
  is its exact position (a *star fix*, *Systems → Star positions*). Name the fix
  as its system; distances between named systems are then exact as the game's map
  shows them (checked on four stars). **Fix:** the positions recorded since the
  exact-positions change were the map camera's position, not the system's - they
  are no longer used (kept in the history file as `positions_discarded`).

- **What your equipment does**: every technology and upgrade module now shows its
  stat modifiers, read from the game's technology tables - an upgrade module every
  stat it can have with its range (*Mining Speed +5-10 %*, *always* marked; the
  game keeps the exact values to itself), fixed technology the range it adds, the
  ability it unlocks or a known value (*Clip Size 64*). In the *What it does*
  column and in the item's tooltip.
- **Equipment tab with sub-tabs**: Exosuit, Multi-tools, **Exocraft** (new: Roamer,
  Nomad, Colossus, Pilgrim, Nautilon, Minotaur, named in the game's languages) and
  Freighter. *Ships & bases* shows **every ship's technology** (one tab per ship),
  not only the primary ship's.
- **Missing texts filled in**: tooltips show the description in the game's
  language too (only English was shown); all 199 upgrade modules get a category
  (*Upgrade Module: Mining Beam*) and, where the game has one, a description
  (they had none); button images in game texts read "[button]" instead of
  "FE_ALT1"; a creature egg's per-item fill-ins (%NAME%, %SIZE%) show as "…".
  The item database is rebuilt once (about a second).
- **Persona setup** (needs the 40k Assistant 3.10.0): while linking the persona
  the plugin page asks for a **Codex library** (libraries named *No Man's Sky*
  are preselected) and **web search** (*when needed* only for a model that can
  search). The persona also answers **equipment questions** ("which upgrades
  does my multi-tool have?") with what each part does.
- **Code structure**: the connector's page, persona, summaries and game tables
  are separate classes (`page.py`, `companion.py`, `describe.py`, `tables.py`);
  the technology tables are read once (`techstats.py`) for both the stat
  modifiers and the warp range.

- **Economies from the galaxy map**: with the galaxy map open the game holds the
  economy, wealth, conflict, race and star colour of the stars around you; the
  plugin reads them every few minutes (~6 s in the background) and traces each
  back to its system through its planets' seeds. Every other known system gets a
  **prediction** from the game's generation rules (ported from nms_namegen, MIT),
  marked *predicted* - so trade routes, the galaxy map's economy and star colours
  and the route planner cover far more systems.
- **The plugin persona answers more**: the contents of an inventory you name
  ("what is in my ship?"), every trade good ("what trade goods do I have?") with
  where it sells and the nearest system that buys it, your settlement's state
  (stats, production, waiting decision, finished construction), and the nearest
  systems of an economy ("nearest scientific system?"). A finished construction
  no longer shows as "in construction".
- **Exact system positions**: the game shows where your current system lies
  inside its region (a render parameter, `gGalacticScale`); the plugin records it
  for every system you visit with the game running. Distances between two such
  systems - on the map, in the trade tables and in the route planner - are now
  exact instead of "same region (< 400 ly)", and the map draws them in place.
- **The No Man's Sky Plugin Persona** (needs the 40k Assistant 3.9.0): the plugin
  brings a persona that answers questions about your game from its live data.
  Link it to a model on the plugin's page, then ask in the chat - "How much
  copper do I have?" gives the total and how much is in each inventory, and
  where it was seen on planets; it also knows your currencies, location, ships
  and warp range, settlements, frigates and timers. Item names work in English
  and in the game's language.
- **Decision timers**: each settlement gets a timer for its next decision, ending at
  the latest moment it can come (2 h after the last); with a bell you are
  notified then.
- **Frigates**: *Ships & bases* lists your frigates with class icon, grade,
  race, combat/exploration/industry/trade values, traits by their in-game names
  (from the game's trait table), expedition record, home system and state (out
  on an expedition, damaged, ready).
- **Equipment**: *Inventory → Equipment* lists the exosuit's technology, every
  multi-tool (class, which one is in your hand, its technology) and the
  freighter's technology, each part with its icon, category and charge.
- **More icons**: planet hints get the game's own icons (bones, grubs, buried
  technology), and the settlement's stats and perks the settlement screen's
  icons (positive or negative for perks).
- **Ships**: *Ships & bases* lists every ship with type, class, its own bonuses,
  slots (and damaged ones), an **estimated warp range** (hyperdrive 100 ly plus
  upgrades - e.g. an S-class upgrade 220-265 ly - and the ship's hyperdrive bonus,
  from the game's technology tables) and the star colours it can reach; the
  primary ship's technology with charge and what each part adds. The route
  planner's jump range starts with the primary ship's estimate. The Overview
  names the primary ship with its range, the freighter with its own range
  (freighter hyperdrive and its upgrades) and each settlement's state.
- **Galaxy map**: shows the systems around you that the game's galaxy map knows
  (small grey points), can colour systems by economy or conflict level, and
  draws the planned route; it can also colour systems by star colour. Those
  systems are also stops for the route planner, which skips stops at star
  colours your primary ship cannot reach yet and warns when the target is one.
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
