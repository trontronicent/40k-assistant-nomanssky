# Changelog

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
