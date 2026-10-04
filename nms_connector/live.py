"""Pacing of the read-only memory reading: when to scan, which system you are in, what was recorded.

A full scan reads ~5 GB (about 3-4 s since 0.9.1, 18 s before), so it runs only when needed:

- when the game (re)starts, or the player-state anchor is lost;
- when the current system changes (the current address is re-read cheaply every
  tick), and once more FOLLOW_UP_S later, because the game generates the other
  planets of a system over the first seconds after arrival;
- otherwise every RESCAN_S.

Where you are comes from the player state when it can be read. The game holds
GcPlayerStateData in that layout only around saves and loads, so usually it
cannot (seen 2026-10-04 after a game restart; a copy found earlier was gone
minutes later). Then the current system is judged from the planet records
(``memory.current_system_from_planets``) and a system change is noticed by
re-reading the PlanetUA of the remembered planet slots every tick - 8 bytes per
planet instead of a 5 GB scan. ``current_source`` says which way it was found;
the planet you are on is only known from the player state. The slots are watched
while a player-state copy is followed too: the game can leave that copy frozen at
the old system and write the new position into a new copy (seen 2026-10-04); after
a scan a copy that changed wins over one that did not (``_pick_player_state``).

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
    def __init__(self, history: PlanetHistory, opener=None, pid_finder=None, scanner=None, star_finder=None):
        self.history = history
        self._open = opener or memory.ProcessReader
        self._find_pid = pid_finder or memory.find_game_pid
        self._scan = scanner or memory.scan
        self._find_stars = star_finder or memory.find_star_attributes
        self.last_economy_systems = 0
        self.reader = None
        self.status = "idle"          # unsupported | not-running | error | ok
        self.error: str | None = None
        self.player_state: int | None = None
        self.player_states: list[int] = []     # every copy the last scan found; the one that moves is live
        self._addresses: dict[int, dict | None] = {}
        self.current: dict | None = None        # current universe address (save layout)
        self.current_system: int | None = None  # packed system key
        self.current_source: str | None = None  # "player" (exact position) | "planets" (judged from memory)
        self.slots: list[int] = []              # planet records of the last scan (warp detection)
        self.name_regions: list[int] = []       # where the last scan found the name cache (star records nearby)
        self.last_scan_at: float | None = None
        self.last_scan_iso: str | None = None
        self.last_scan_seconds: float | None = None
        self.last_scan_bytes = 0
        self.last_scan_planets = 0
        self._scanned_system: int | None = None
        self._slots_system: int | None = None   # majority system of the planet slots at the last scan
        self._scanned_with_anchor: bytes | None = None
        self._follow_up_at: float | None = None

    def close(self) -> None:
        if self.reader is not None:
            self.reader.close()
            self.reader = None
        self.player_state = None
        self.player_states, self._addresses = [], {}
        self.slots = []

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
            self.current_source = None
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
                # The copy is only trusted while the save's start addresses are still in front of it: once the
                # game reuses that memory, the address field holds whatever bytes landed there.
                intact = not anchor or self.reader.read(self.player_state, len(anchor)) == anchor
                ua = memory.read_current_address(self.reader, self.player_state) if intact else None
                if ua is None:
                    self.player_state, self.current, due = None, None, True
                else:
                    self._set_current(ua)
                    if self.current_system != self._scanned_system:
                        due = True
                        self._follow_up_at = now + FOLLOW_UP_S
            # The planet slots are watched even while a copy is followed: that copy can stay frozen at the old
            # system while the game writes the new position into a copy elsewhere (seen 2026-10-04).
            if not due and self.slots:
                judged = self._system_from_slots()
                if judged is not None and judged != self._slots_system:
                    due = True
                    self._follow_up_at = now + FOLLOW_UP_S
            if self._follow_up_at is not None and now >= self._follow_up_at:
                due, self._follow_up_at = True, None
            if not due:
                self.status, self.error = "ok", None
                return 0
            result = self._scan(self.reader, substances, anchor)
            addresses = {a: memory.read_current_address(self.reader, a) for a in result.player_states}
            self.player_state, ua = self._pick_player_state(result, addresses)
            self.player_states = list(result.player_states)
            self._addresses = addresses
            if ua is not None:
                self._set_current(ua)
            else:
                self.current = None
                self.current_system = result.majority_system()
                self.current_source = "planets" if self.current_system is not None else None
            self.slots = list(result.slots)
            self._slots_system = result.majority_system()
            self.name_regions = list(result.name_regions)
            self._scanned_system = self.current_system
            self._scanned_with_anchor = anchor
            self.last_scan_at = now
            self.last_scan_iso = datetime.now().isoformat(timespec="seconds")
            self.last_scan_seconds, self.last_scan_bytes = result.seconds, result.bytes_read
            self.last_scan_planets = len(result.planets)
            changed = self.history.record(result.planets, self.last_scan_iso, self.current_system)
            changed += self._read_economies(result.planets)
            changed += self.history.record_system_names(result.system_names)
            self.history.save()   # always: the scan log is part of the file
            self.status, self.error = "ok", None
            return changed
        except memory.MemoryUnavailable as exc:
            self.close()
            self.status, self.error = "error", str(exc)
            return 0

    def _pick_player_state(self, result, addresses: dict[int, dict | None]) -> tuple[int | None, dict | None]:
        """The player-state copy to follow after a scan, and its address.

        A copy that is new since the last scan or whose address changed is live; one that kept its address
        may be frozen. So: the followed copy if it changed; else a changed copy (preferring one whose system
        has planets in memory); else the followed copy while it is still readable; else the scan's pick. On
        the first scan nothing is known yet and the scan's pick decides.
        """
        previous = self.player_state
        changed = [a for a in result.player_states if addresses.get(a) is not None and self._addresses
                   and (a not in self._addresses or self._addresses[a] != addresses[a])]
        if previous in changed:
            return previous, addresses[previous]
        if changed:
            return result.best_player_state(self.reader, changed)
        if previous in result.player_states and addresses.get(previous) is not None:
            return previous, addresses[previous]
        return result.best_player_state(self.reader)

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

    def _read_economies(self, planets: list[dict]) -> int:
        """Economy, wealth, conflict and race of the systems in this scan that have none recorded yet.

        Found through the planets' seeds in the galaxy map's star records (memory.find_star_attributes): one
        more pass over memory, only when a new system turned up. The planets of the history count too, so a
        system read before keeps matching all its known planets.
        """
        missing = {p["system"] for p in planets if p.get("seed")} - set(self.history.economies)
        if not missing:
            return 0
        known = {key: plist for key, plist in self.history.systems().items() if key in missing}
        found = self._find_stars(self.reader, known, self.name_regions)
        self.last_economy_systems = len(found)
        return self.history.record_economies(found, self.last_scan_iso)

    def _system_from_slots(self) -> int | None:
        """The majority system of the remembered planet slots as they are now (None when none is a planet)."""
        systems = [memory.planet_system_at(self.reader, address) for address in self.slots]
        return memory.current_system_from_planets([{"system": s} for s in systems if s is not None])

    def _set_current(self, ua: dict) -> None:
        self.current = ua
        self.current_system = memory.system_key(memory.pack_address(ua))
        self.current_source = "player"
