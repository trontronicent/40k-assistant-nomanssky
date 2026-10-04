# No Man's Sky

A companion for No Man's Sky: it reads your save files and - while the game
runs - the game's memory, and shows what you have, where you are and every
system you visited. It only reads: nothing in the game or its folders is ever
changed, and the game process is never modified.

Made by **Reto Kummer alias Reat Kay**. The credits for the work this plugin builds on are
listed at the end of this section.

## The page

Open it from **Plugins → No Man's Sky** in the header. The buttons at the top:

- **Rescan** - read the newest save file again now.
- **Scan game now** - read the planets of the current system from the running game now (takes 1-2 seconds).
- **Update key mapping** - download the newest key list after a game update (when the page reports unknown keys).
- **Re-read item names** - read item names and icons from the game files again, for example after changing the game's language in Steam.
- **Clear save history** - forget the recorded save writes.

The tabs:

- **Overview** - **timers** (when your settlement buildings are finished and your frigate expeditions return), units, nanites, quicksilver, health, where you were at the last save, where you are now, your fleet and companions: the **primary ship** with its estimated warp range and the star colours it reaches, your **settlements** at a glance (construction, a decision waiting), the **freighter** with its warp range, and the current mission in the game's words.
- **Systems** - *Current system* (live from the game, with a map), *Visited systems* (every system from your save; click one to see its map), *Planets* (every planet whose resources were read), *Galaxy* (the galaxy map and the nearest planet with each resource) and *Trade* (economies and trade routes) and *Route* (the route planner).
- **Inventory** - exosuit, starship, freighter and **storage containers** (0-9, numbered as in the game), each item with its icon, its name in English and in the game's language, and its **category**. Hover an item's name for its description; **trade goods** also tell which economies pay well for them, the nearest such system you know (or that you have not found one yet) and where they are cheap to buy. Planet resources have the same tooltip.
- **Ships & bases** - your ships (type, class, estimated **warp range**, the star colours they can reach, base stats, slots) and the primary ship's technology; your bases with portal addresses. See *Ships* below.
- **Settlements** - the economy of each settlement you run: see *Settlements* below.
- **Saves & source** - how often the game saves, the recent save writes, where the data comes from and the last memory scans.

## Timers

At the top of the *Overview* tab: when the building under construction in each of
your **settlements** is finished, and when your **frigate expeditions** return
(with the time of the next expedition event). The save stores when they started;
how long they take comes from the game's own files (a factory, for example, takes
1 h 33 min). New ones appear after the game's next save: the game does not save
on a timer, but when you leave your ship, warp or use a save point (*Saves &
source* shows how often it did). **Rescan** does not help before that - it only
reads the newest save again.

Press a timer's **bell** to be notified when it ends, or **Notify for all
timers**. Turn on notifications for each device with **Turn on notifications on
this device** below the timers (on a phone: open the app through the Vox-Link QR
phone link first) and try **Test**. Notifications arrive even when the page is
closed. With a 40k Assistant older than 3.8.0 the timers show as a table of end
times, without countdown and bells.

## Settlements

One block per settlement you run, from the save:

- **Population**, race, the construction in progress, and the **next decision**:
  the game waits between 15 minutes and 2 hours after a decision before it asks
  the next one (both limits from the game's files), so the tab shows that window,
  or that a decision is waiting for you.
- **Stats** - as the settlement's screen shows them: population (20 / 52),
  happiness and sentinel alert in percent, productivity and maintenance in units
  per day. The game computes these from your buildings and perks only while the
  settlement's screen is open, so open it once (at the settlement's terminal):
  the plugin reads them within about 15 seconds and keeps them until the next
  time (the column heading says when). Next to them, the values the save stores, which are different.
- **Production** - what the settlement makes, how much was ready at your last
  visit and how much it holds at most.
- **Perks** - each with its name (English and your game's language), whether it
  is positive or negative, which stats it makes better or worse, and whether it
  came with the settlement or from a decision. Perks from decisions get their
  name from the game at random, so the tab shows what they do instead.

## Live data

While No Man's Sky runs, the plugin reads the planets of the system you are
in: name (and the name someone uploaded), type, weather, three resources, the
plant resource, the gas an atmosphere harvester collects, flora, fauna and
sentinels. Every planet it sees is remembered, so the *Planets* tab grows as you
travel. Planet resources are not stored in the save, so systems you visited
before using the plugin show their names, but no resources until you go back.

Systems nobody renamed show the **name the game made up** for them (for example
*Ulebsk*), read from the galaxy map's data while the game runs. The game only
keeps the names of the systems around you, so a system you visited long ago may
show as *System <portal address>* until you come near it again; a name, once
read, is remembered. A renamed system shows its uploaded name, and its original
name as *Generated name* under *Where you are*.

Your exact position (the planet you are on) can only be read around saves and
loads; the rest of the time the plugin tells your system from the planets the
game has loaded. The planet then comes from your newest save when that save is
in the same system (shown with the save's time - the game saves about once a
minute while you play); otherwise it shows as *unknown*. Save in the game and
press **Scan game now** to get it.

Live data needs Windows. If the game runs as administrator, the app must too.

## The system map

A system map shows the star (portal address, region, system index, who named
it, when it was discovered, your bases there, and whether it is a black hole,
Atlas or purple-star system) and its planets, coloured by biome and sized by
class. Click a planet for its resources, gas, weather, flora, fauna, sentinels
and your discoveries there. Planets known only from your save appear as *not
scanned yet*.

## Ships

*Ships & bases* lists your ships with type, class, the ship's own bonuses
(damage, shield, hyperdrive, maneuverability), the slots (general / cargo /
technology, and how many are still damaged) and:

- **Warp range (estimate)** - the game does not store it, it adds up the
  hyperdrive technology: the hyperdrive itself (100 ly), hyperdrive upgrades
  (an S-class upgrade adds 220-265 ly: the game picks the exact value from the
  upgrade's seed, so only the range is known) and the ship's own hyperdrive
  bonus. Hover the value to see what it is made of. Adjacent and supercharged
  slots can add more.
- **Star colours it can reach** - red, green, blue and purple stars need the
  matching hyperdrive upgrades (Cadmium, Emeril, Indium drive and the Atlas one).

Below, the primary ship's technology: charge, and what each part adds. The route
planner starts with the lower warp range of your primary ship.

## The galaxy map

*Systems → Galaxy* shows every system you know in the galaxy you are in -
including the systems around you that the game's own galaxy map showed (small
grey points, *not visited*). **Colour systems by** what you know there, their
**economy**, their **conflict level** or their **star colour**, and press **Show**. A route planned
in *Route* is drawn as a dashed red line. Drag
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

## Economy and trade

Every system has an economy (Mining, Technology, Trading, Manufacturing,
Advanced Materials, Scientific or Power Generation), a wealth level, a
conflict level and a dominant race. The plugin reads them from the game's
galaxy map data while you are in a system with the game running, and keeps
them. Systems you visited before this version show theirs after your next
visit.

Each economy sells one kind of trade goods cheaply and pays well for another;
the plugin reads this from the game's trading table. You see it:

- on the star of every **system map** (*Cheap to buy here* and *Sells well here*, with the five trade goods of each kind),
- in the *Economy* and *Conflict* columns of **Visited systems**,
- in **Systems → Trade**: the economies of your systems, and **trade routes** - for every kind of goods, the nearest of your systems to buy it cheaply and the nearest to sell it well. Where none of your systems fits, the table says which economy to look for.

Prices also move with what you buy and sell, and wealthier systems trade the
higher tiers.

## Route planner

> **Work in progress:** the route planner is very much work in progress. Distances
> are estimated from regions (about 400 light years per step, a community figure
> not yet checked against the game), the exact position of a system inside its
> region is unknown, and routes have not been tested in the game yet. Use them as a
> rough guide and check the jumps on the in-game galaxy map.

*Systems → Route*: choose a target - one of your known systems, or **any system
by its portal address** (12 glyphs as hex digits) - and your ship's **jump
range** in light years, and press **Plan route**.

The jump range starts with your primary ship's estimated warp range (the lower
value, see *Ships*); change it when you know better. Stops at red, green, blue
or purple stars are only used when your primary ship has the hyperdrive upgrade
for that colour, and a target your ship cannot reach yet is pointed out.

A jump costs one warp cell however far it goes within your range, so the route
has the **fewest jumps**. Your known systems - including those the game's galaxy
map showed around you - are used as stops where they cost
no extra jump; where none is close enough, a leg crosses unknown space in
several jumps and names the region to aim for on each one - on the galaxy map,
pick a star near that region. The route is listed leg by leg and drawn on a
map; the last route and range are kept. As you travel, the route is planned
again from where you are, and in the target system it says you have arrived.

Distances are measured between regions and are approximate, so leave some
margin on the range.

## Good to know

- Items whose name the game makes up from a seed (salvaged and biological finds such as `PROC_LOOT`) keep their id.
- The current mission (Overview) is shown with the game's own description of it.
- The gas per biome is community knowledge, not read from the game.
- Your save data (base and ship names, inventories) is shown to anyone who can open your app.
