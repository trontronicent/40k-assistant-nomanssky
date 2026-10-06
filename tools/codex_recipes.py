"""Write the No Man's Sky item documents (where each item comes from, every recipe, its uses) into a Codex folder.

    python tools/codex_recipes.py "J:\\40k-assistant\\knowledge_base\\No Man's Sky"

Reads the installed game (recipe and item tables) and the plugin's item cache for names and descriptions
(--items, default: the app's plugins/.data/nomanssky/gamedata/items.json). Only files under Items/ that carry the
generator's mark are written or removed; the app's Codex folder sync then indexes them. Run it again after a game
update. See nms_connector/recipes.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nms_connector.recipes import main  # noqa: E402  (after the path set-up)

if __name__ == "__main__":
    raise SystemExit(main())
