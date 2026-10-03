"""Detect when the game writes a save, and record it (pure state machine).

``poll(files, now)`` is called every few seconds with the current save files.
A changed file is only reported once its size and modification time have stayed
the same for ``settle_s`` seconds, so a save is never read while the game is
still writing it. Every settled write becomes an event; the events answer
"how often does the game save while I play?".
"""

from __future__ import annotations

import statistics
from datetime import datetime

from .saves import SaveFile

SESSION_GAP_S = 2 * 3600   # intervals longer than this span a break, not play


class SaveWatcher:
    def __init__(self, settle_s: float = 2.0, max_events: int = 300, events: list[dict] | None = None):
        self.settle_s = settle_s
        self.max_events = max_events
        self.events: list[dict] = list(events or [])[-max_events:]
        self._known: dict[str, tuple[int, float]] = {}
        self._pending: dict[str, tuple[int, float, float]] = {}
        self._baseline_done = False

    def poll(self, files: list[SaveFile], now: float) -> list[SaveFile]:
        """Return save files that have a new, settled write (the first poll returns the newest file)."""
        if not self._baseline_done:
            self._baseline_done = True
            for f in files:
                self._known[str(f.path)] = (f.size, f.mtime)
            return [max(files, key=lambda f: f.mtime)] if files else []

        ready = []
        for f in files:
            key, sig = str(f.path), (f.size, f.mtime)
            if self._known.get(key) == sig:
                self._pending.pop(key, None)
                continue
            pending = self._pending.get(key)
            if pending is None or pending[:2] != sig:
                self._pending[key] = (f.size, f.mtime, now)
                continue
            if now - pending[2] >= self.settle_s:
                self._known[key] = sig
                del self._pending[key]
                self._record(f)
                ready.append(f)
        return ready

    def _record(self, f: SaveFile) -> None:
        previous = self.events[-1]["mtime"] if self.events else None
        self.events.append({
            "at": datetime.fromtimestamp(f.mtime).isoformat(timespec="seconds"),
            "mtime": f.mtime, "file": f.path.name, "slot": f.slot, "size": f.size,
            "since_previous_s": round(f.mtime - previous, 1) if previous is not None else None,
        })
        del self.events[:-self.max_events]

    def stats(self) -> dict:
        """Count and typical spacing of saves during play (breaks over 2 h excluded)."""
        gaps = [e["since_previous_s"] for e in self.events
                if e.get("since_previous_s") is not None and 0 < e["since_previous_s"] <= SESSION_GAP_S]
        return {
            "writes": len(self.events),
            "median_interval_s": statistics.median(gaps) if gaps else None,
            "shortest_interval_s": min(gaps) if gaps else None,
            "longest_interval_s": max(gaps) if gaps else None,
        }
