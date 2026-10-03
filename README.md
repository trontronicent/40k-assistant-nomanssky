# No Man's Sky connector for the 40k Assistant

A plugin (STC) for the [40k Assistant / Strategicum](https://github.com/trontronicent/40k-assistant).
It reads your **No Man's Sky save files** and shows what a companion needs to
know. Install it from the app's **Plugins → Manage plugins** page.

## What it shows

- **Status:** units, nanites, quicksilver, health, shield, ship health, play time
- **Location at the last save:** galaxy, portal address (12 hex glyphs), region,
  system and planet index, your bases in that system
- **Inventories:** exosuit, primary starship, freighter (item ids such as `CATALYST1`)
- **Ships, bases, frigates, expeditions, companions, current mission id**
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

## Permissions

`read-game-files` (the save folder) and `network` (downloading `mapping.json`
from GitHub). Like every code plugin it runs inside the 40k Assistant backend,
which is why the app asks you to confirm that you trust it before installing.

No Man's Sky has no anti-cheat, and the plugin does not touch the game process.

## Privacy

Save data (base names, ship names, inventories) is shown on the app's plugin
page. Anyone who can reach your 40k Assistant (LAN, tunnel) can read it there.

## Development

Python 3.11+, standard library only.

```
python -m pytest tests
```

## License

MIT, see [LICENSE](LICENSE).
