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
