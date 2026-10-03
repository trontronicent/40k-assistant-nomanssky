"""Pacing of the read-only memory reading: when to scan, which system you are in, what was recorded.

A full scan costs ~6-13 s of reading, so it runs only when needed:

- when the game (re)starts, or the player-state anchor is lost;
- when the current system changes (the current address is re-read cheaply every
  tick), and once more FOLLOW_UP_S later, because the game generates the other
  planets of a system over the first seconds after arrival;
- otherwise every RESCAN_S.

Blocking throughout; the plugin calls tick() through ctx.run_blocking.
"""

from __future__ import annotations

import sys
from datetime import datetime

from . import memory
from .history import PlanetHistory

RESCAN_S = 300
FOLLOW_UP_S = 45


class LiveMemory:
    def __init__(self, history: PlanetHistory, opener=None, pid_finder=None, scanner=None):
        self.history = history
        self._open = opener or memory.ProcessReader
        self._find_pid = pid_finder or memory.find_game_pid
        self._scan = scanner or memory.scan
        self.reader = None
        self.status = "idle"          # unsupported | not-running | error | ok
        self.error: str | None = None
        self.player_state: int | None = None
        self.player_states: list[int] = []     # every copy the last scan found; the one that moves is live
        self._addresses: dict[int, dict | None] = {}
        self.current: dict | None = None        # current universe address (save layout)
        self.current_system: int | None = None  # packed system key
        self.last_scan_at: float | None = None
        self.last_scan_iso: str | None = None
        self.last_scan_seconds: float | None = None
        self.last_scan_bytes = 0
        self.last_scan_planets = 0
        self._scanned_system: int | None = None
        self._scanned_with_anchor: bytes | None = None
        self._follow_up_at: float | None = None

    def close(self) -> None:
        if self.reader is not None:
            self.reader.close()
            self.reader = None
        self.player_state = None
        self.player_states, self._addresses = [], {}

    def tick(self, anchor: bytes | None, substances: set[str] | None, now: float) -> int:
        """One step; returns how many planet records were new or changed."""
        if sys.platform != "win32" and self._open is memory.ProcessReader:
            self.status, self.error = "unsupported", "reading the game's memory is only supported on Windows"
            return 0
        try:
            pid = self._find_pid()
        except memory.MemoryUnavailable as exc:
            self.status, self.error = "error", str(exc)
            return 0
        if pid is None:
            self.close()
            self.status, self.error, self.current, self.current_system = "not-running", None, None, None
            return 0
        try:
            if self.reader is None or getattr(self.reader, "pid", None) != pid:
                self.close()
                self.reader = self._open(pid)
                self.last_scan_at = None
            due = self.last_scan_at is None or now - self.last_scan_at >= RESCAN_S
            # The anchor comes from the save; once it is known (or changes), find the player state right away.
            if anchor and self.player_state is None and anchor != self._scanned_with_anchor:
                due = True
            if self.player_state is not None:
                self._follow_moving_copy()
                ua = memory.read_current_address(self.reader, self.player_state)
                if ua is None:
                    self.player_state, due = None, True
                else:
                    self._set_current(ua)
                    if self.current_system != self._scanned_system:
                        due = True
                        self._follow_up_at = now + FOLLOW_UP_S
            if self._follow_up_at is not None and now >= self._follow_up_at:
                due, self._follow_up_at = True, None
            if not due:
                self.status, self.error = "ok", None
                return 0
            result = self._scan(self.reader, substances, anchor)
            previous = self.player_state
            self.player_state, ua = result.best_player_state(self.reader)
            if previous in result.player_states:   # still there: keep it (it may be the copy seen moving)
                kept = memory.read_current_address(self.reader, previous)
                if kept is not None:
                    self.player_state, ua = previous, kept
            self.player_states = list(result.player_states)
            self._addresses = {a: memory.read_current_address(self.reader, a) for a in self.player_states}
            if ua is not None:
                self._set_current(ua)
            self._scanned_system = self.current_system
            self._scanned_with_anchor = anchor
            self.last_scan_at = now
            self.last_scan_iso = datetime.now().isoformat(timespec="seconds")
            self.last_scan_seconds, self.last_scan_bytes = result.seconds, result.bytes_read
            self.last_scan_planets = len(result.planets)
            changed = self.history.record(result.planets, self.last_scan_iso, self.current_system)
            self.history.save()   # always: the scan log is part of the file
            self.status, self.error = "ok", None
            return changed
        except memory.MemoryUnavailable as exc:
            self.close()
            self.status, self.error = "error", str(exc)
            return 0

    def _follow_moving_copy(self) -> None:
        """Switch to a player-state copy whose address changed since the last tick while ours did not.

        The game keeps more than one copy of the player state; the scan picks one by a heuristic, but only
        the live copy changes when you travel, so a copy that moves is the one to follow.
        """
        moved = []
        for address in self.player_states:
            ua = memory.read_current_address(self.reader, address)
            if ua is not None and self._addresses.get(address) not in (None, ua):
                moved.append(address)
            self._addresses[address] = ua
        if moved and self.player_state not in moved:
            self.player_state = moved[0]

    def _set_current(self, ua: dict) -> None:
        self.current = ua
        self.current_system = memory.system_key(memory.pack_address(ua))
