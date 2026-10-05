"""One-line texts about the player's state, shared by the page (Overview) and the persona's chat data.

``StateText`` reads the connector's current state (ships, freighter, settlements, timers, game texts) each time
it is asked, so it never holds a stale copy.
"""

from __future__ import annotations

import re
import time

from . import ships
from .summary import mission_text_keys

MISSION_CHARS = 220


class StateText:
    """Texts such as 'Bang (Fighter, class C) - warp range ~320-365 ly, red stars' about one connector's state."""

    def __init__(self, connector):
        self.connector = connector

    def primary_ship(self) -> str:
        """'Bang (Fighter, class C) - warp range ~320-365 ly, red and green stars' (details in Ships & bases)."""
        c = self.connector
        primary = next((s for s in c.ships if s["primary"]), None)
        if primary is None:
            return "none"
        est = ships.warp_range(primary, c.tables.ship_ranges)
        stars = f", {' and '.join(est['colours'])} stars" if est["colours"] else ""
        return f"{ships.ship_label(primary)} ({primary['type']}, class {primary['class']}) - warp range {ships.range_text(est)}{stars}"

    def freighter(self, name: str | None) -> str:
        """'Iron Maiden (class S) - warp range ~100 ly' (the freighter's hyperdrive, estimated like a ship's)."""
        c = self.connector
        label = name or "(unnamed)"
        if not c.freighter:
            return label
        est = ships.freighter_range(c.freighter, c.tables.ship_ranges)
        return f"{label} (class {c.freighter['class']}) - warp range {ships.range_text(est)}"

    def settlements(self) -> str:
        """'Kay City: Farm in construction, a decision is waiting' - one part per settlement."""
        c = self.connector
        if not c.settlements:
            return "none"
        parts = []
        now = time.time()
        for s in c.settlements:
            build = next((t for t in c.timers if t["key"].startswith("settlement.") and s["name"] in t["label"]), None)
            # The save keeps the building after it is finished (until you claim it): the timer tells which.
            if build and build["ends_at"] <= now:
                bits = [f"{s['building'] or 'construction'} finished"]
            else:
                bits = [f"{s['building']} in construction"] if s.get("building") else []
            if s.get("pending") and s["pending"] != "None":
                bits.append("a decision is waiting")
            parts.append(f"{s['name']}: {', '.join(bits)}" if bits else s["name"])
        return "; ".join(parts) + " (see Settlements)"

    def mission(self, mission_id: str | None) -> str:
        """The current mission as the game describes it, with its id; the id alone when no text is known."""
        if not mission_id:
            return "none"
        for key in mission_text_keys(mission_id):
            entry = self.connector.gamedata.text(key)
            if entry:
                # One line, without the game's fill-ins ("%PLANET%", "%SETTLEMENT%": the game names them in play).
                text = " ".join(re.sub(r"%[A-Z0-9_]+%", "it", entry["en"]).split())
                if len(text) > MISSION_CHARS:
                    text = text[:MISSION_CHARS - 3].rsplit(" ", 1)[0] + "..."
                return f"{text} ({mission_id})"
        return mission_id
