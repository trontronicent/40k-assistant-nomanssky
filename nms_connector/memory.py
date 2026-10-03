"""Read the running game's memory - read-only, Windows only.

The process is opened with PROCESS_QUERY_INFORMATION | PROCESS_VM_READ: the
handle cannot write, inject or change anything in the game (No Man's Sky has
no anti-cheat). Planets are found by their data, not by code addresses, so
nothing has to be updated for a new game executable as long as the data
layouts below still hold; every record is validated before it is used.

What is read:

- ``GcPlanetData`` (layout as MBINCompiler's libMBIN describes it; the MBIN
  layout is the in-memory layout): one per generated planet of the current
  system, plus stale slots of earlier systems. Found by the three substance
  ids at fixed offsets, validated by name, planet index and
  ``BuildingData.PlanetUA`` (the planet's packed universe address, whose planet
  nibble is index + 1).
- The player's current universe address in ``GcPlayerStateData``, found via
  ``GameStartAddress1/2`` (fixed per save, taken from the save file) which sit
  0x90 bytes before ``UniverseAddress``.

Scanning reads the game's private read/write memory (~5 GB) in 64 MB chunks
and takes about 6 s; numpy (part of the 40k Assistant) does the filtering.
"""

from __future__ import annotations

import re
import struct
import sys
from dataclasses import dataclass

try:
    import numpy as np
except ImportError:  # pragma: no cover - the host ships numpy
    np = None

GAME_EXE = "nms.exe"
CHUNK = 64 << 20

# GcPlanetData (libMBIN 7.04): offsets inside the record.
PLANET_SIZE = 0x3AD2
P_COMMON = 0x33D0
P_EXTRA_HINTS = 0x33F0       # List<GcPlanetDataResourceHint>: {pointer u64, count u32, ...}; hint = 0x20 bytes
P_RARE = 0x3400
P_UNCOMMON = 0x3430
P_INDEX = 0x353C
P_LIFE = 0x3538
P_CREATURE_LIFE = 0x352C
P_RACE = 0x3534
P_INFO = 0x3548              # GcPlanetInfo: 0x80-byte strings
P_NAME = 0x3A4E
P_PLANET_UA = 0x3338 + 0x30  # BuildingData.PlanetUA
P_GENERATION = 0x3180        # GcPlanetGenerationIntermediateData
INFO_FIELDS = {"sentinels": [0x000, 0x080, 0x100, 0x180], "fauna": 0x200, "flora": 0x280, "description": 0x300,
               "type": 0x380, "resources": 0x400, "weather": 0x480}
INFO_EXTREME_WEATHER = 0x504
INFO_SPECIAL_FAUNA = 0x505

# GcPlayerStateData: GameStartAddress1 at 0x865C8, UniverseAddress at 0x86658.
UA_AFTER_GAME_START = 0x86658 - 0x865C8
UA_STRUCT = struct.Struct("<6i")   # PlanetIndex, SolarSystemIndex, VoxelX, VoxelY, VoxelZ, RealityIndex

ID_RE = re.compile(rb"^[A-Z][A-Z0-9_]{1,14}$")
BIOMES = ["Lush", "Toxic", "Scorched", "Radioactive", "Frozen", "Barren", "Dead", "Exotic", "Exotic (red)",
          "Exotic (green)", "Exotic (blue)", "Test", "Swamp", "Lava", "Waterworld", "Gas giant"]
SIZES = ["Large", "Medium", "Small", "Moon", "Giant"]


class MemoryUnavailable(RuntimeError):
    """The game's memory cannot be read here (not Windows, not running, access denied, no numpy)."""


def fixed(buf: bytes, offset: int, size: int) -> bytes | None:
    field = buf[offset:offset + size]
    end = field.find(b"\0")
    return field[:end] if end >= 0 else None


def text(buf: bytes, offset: int, size: int) -> str | None:
    raw = fixed(buf, offset, size)
    if not raw:
        return None
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return value if value.isprintable() else None


def system_key(packed: int) -> int:
    """The packed address of a planet or system with the planet nibble cleared: one key per system."""
    return packed & ~(0xF << 52)


def pack_address(ua: dict) -> int:
    """Universe address dict (save layout) -> packed u64, as used by PlanetUA and the save's VisitedSystems."""
    g = ua["GalacticAddress"]
    return ((g["VoxelX"] & 0xFFF) | (g["VoxelZ"] & 0xFFF) << 12 | (g["VoxelY"] & 0xFF) << 24
            | (ua.get("RealityIndex", 0) & 0xFF) << 32 | (g["SolarSystemIndex"] & 0xFFF) << 40
            | (g["PlanetIndex"] & 0xF) << 52)


def ua_bytes(ua: dict) -> bytes:
    g = ua["GalacticAddress"]
    return UA_STRUCT.pack(g["PlanetIndex"], g["SolarSystemIndex"], g["VoxelX"], g["VoxelY"], g["VoxelZ"],
                          ua.get("RealityIndex", 0))


def ua_from_bytes(raw: bytes) -> dict | None:
    planet, system, x, y, z, reality = UA_STRUCT.unpack(raw)
    if not (0 <= planet < 16 and 0 <= system < 0x1000 and -2048 <= x < 2048 and -128 <= y < 128
            and -2048 <= z < 2048 and 0 <= reality < 256):
        return None
    return {"RealityIndex": reality, "GalacticAddress": {"PlanetIndex": planet, "SolarSystemIndex": system,
                                                         "VoxelX": x, "VoxelY": y, "VoxelZ": z}}


def parse_planet(blob: bytes, read=None, substances: set[str] | None = None) -> dict | None:
    """A validated planet record from a GcPlanetData blob, or None when the blob is not one."""
    if len(blob) < PLANET_SIZE:
        return None
    ids = [fixed(blob, off, 16) for off in (P_COMMON, P_UNCOMMON, P_RARE)]
    if not all(i and ID_RE.match(i) for i in ids):
        return None
    ids = [i.decode() for i in ids]
    if substances is not None and not all(i in substances for i in ids):
        return None
    name = text(blob, P_NAME, 0x80)
    index = struct.unpack_from("<i", blob, P_INDEX)[0]
    ua = struct.unpack_from("<Q", blob, P_PLANET_UA)[0]
    if not name or not 0 <= index < 16 or ua >> 56 or (ua >> 52) & 0xF != index + 1:
        return None
    info = {}
    for key, off in INFO_FIELDS.items():
        if isinstance(off, list):
            info[key] = [text(blob, P_INFO + o, 0x80) for o in off]
        else:
            info[key] = text(blob, P_INFO + off, 0x80)
    if not info["type"] or not info["weather"]:
        return None
    biome, subtype, _class, size = struct.unpack_from("<4i", blob, P_GENERATION + 0x138)
    extra: list[str] = []
    pointer, count = struct.unpack_from("<QI", blob, P_EXTRA_HINTS)
    if read is not None and 0 < count <= 16 and pointer:
        hints = read(pointer, count * 0x20)
        if hints and len(hints) == count * 0x20:
            for i in range(count):
                hint = fixed(hints, i * 0x20, 16)
                if hint and ID_RE.match(hint):
                    extra.append(hint.decode())
    return {
        "ua": ua, "system": system_key(ua), "index": index, "name": name,
        "common": ids[0], "uncommon": ids[1], "rare": ids[2], "extra": extra,
        "biome": BIOMES[biome] if 0 <= biome < len(BIOMES) else None,
        "biome_subtype": subtype, "size": SIZES[size] if 0 <= size < len(SIZES) else None,
        "info": info, "extreme_weather": bool(blob[P_INFO + INFO_EXTREME_WEATHER]),
        "special_fauna": bool(blob[P_INFO + INFO_SPECIAL_FAUNA]),
    }


def candidate_rows(buf: bytes):
    """Offsets of 16-byte-aligned rows where common/rare/uncommon id strings sit 0x30 apart."""
    n = len(buf) // 16
    if n < 8:
        return []
    rows = np.frombuffer(buf, np.uint8, n * 16).reshape(n, 16)
    first, second = rows[:, 0], rows[:, 1]
    ok = (first >= 65) & (first <= 90) & (((second >= 65) & (second <= 90)) | ((second >= 48) & (second <= 57))
                                         | (second == 95))
    hit = ok[:-6] & ok[3:-3] & ok[6:]
    return (np.nonzero(hit)[0] * 16).tolist()


@dataclass
class ScanResult:
    planets: list[dict]
    player_states: list[int]     # every copy of GcPlayerStateData found by the anchor (usually one or two)
    bytes_read: int
    seconds: float

    def best_player_state(self, reader) -> tuple[int | None, dict | None]:
        """The player-state copy to follow: prefer one whose current system has planets in this scan."""
        systems = {p["system"] for p in self.planets}
        fallback: tuple[int | None, dict | None] = (None, None)
        for address in self.player_states:
            ua = read_current_address(reader, address)
            if ua is None:
                continue
            if system_key(pack_address(ua)) in systems:
                return address, ua
            if fallback[0] is None:
                fallback = (address, ua)
        return fallback


class ProcessReader:
    """A read-only handle on the game process (Windows)."""

    def __init__(self, pid: int):
        if sys.platform != "win32":
            raise MemoryUnavailable("reading the game's memory is only supported on Windows")
        if np is None:
            raise MemoryUnavailable("reading the game's memory needs numpy (part of the 40k Assistant)")
        import ctypes
        import ctypes.wintypes as wt

        class MBI(ctypes.Structure):
            _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                        ("AllocationProtect", wt.DWORD), ("PartitionId", wt.WORD), ("RegionSize", ctypes.c_size_t),
                        ("State", wt.DWORD), ("Protect", wt.DWORD), ("Type", wt.DWORD)]

        self._ct, self._MBI = ctypes, MBI
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wt.HANDLE
        k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
        k32.VirtualQueryEx.restype = ctypes.c_size_t
        k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                          ctypes.POINTER(ctypes.c_size_t)]
        k32.ReadProcessMemory.restype = wt.BOOL
        k32.CloseHandle.argtypes = [wt.HANDLE]
        self._k32 = k32
        # Read-only rights: query + read. No PROCESS_VM_WRITE / VM_OPERATION / CREATE_THREAD.
        self._handle = k32.OpenProcess(0x0400 | 0x0010, False, pid)
        if not self._handle:
            raise MemoryUnavailable(f"cannot open the game process (Windows error {ctypes.get_last_error()}; "
                                    "if the game runs as administrator, the app must too)")
        self.pid = pid

    def close(self) -> None:
        if self._handle:
            self._k32.CloseHandle(self._handle)
            self._handle = None

    def regions(self):
        """(base, size) of committed private read/write regions - where the game's heap data lives."""
        mbi = self._MBI()
        addr = 0
        while self._k32.VirtualQueryEx(self._handle, self._ct.c_void_p(addr), self._ct.byref(mbi), self._ct.sizeof(mbi)):
            base, size = mbi.BaseAddress or 0, mbi.RegionSize
            if mbi.State == 0x1000 and mbi.Type == 0x20000 and mbi.Protect == 0x04:
                yield base, size
            addr = base + size
            if addr >= 0x7FFFFFFFFFFF:
                break

    def read(self, address: int, size: int) -> bytes | None:
        buf = self._ct.create_string_buffer(size)
        done = self._ct.c_size_t()
        if not self._k32.ReadProcessMemory(self._handle, self._ct.c_void_p(address), buf, size, self._ct.byref(done)):
            return None
        return buf.raw[:done.value]


def scan(reader, substances: set[str] | None, anchor: bytes | None, clock=None) -> ScanResult:
    """Find every planet record (and, with the save's GameStartAddress anchor, the player state)."""
    import time
    clock = clock or time.perf_counter
    started = clock()
    planets: dict[tuple[int, str], dict] = {}
    player_states: list[int] = []
    total = 0
    for base, size in reader.regions():
        for offset in range(0, size, CHUNK):
            length = min(CHUNK, size - offset)
            # Overlap the next chunk a little so a record split across chunks is still seen whole.
            buf = reader.read(base + offset, min(length + PLANET_SIZE, size - offset))
            if not buf:
                continue
            total += min(len(buf), length)
            if anchor:
                at = buf.find(anchor)
                while 0 <= at < length:
                    ua = ua_from_bytes(buf[at + UA_AFTER_GAME_START:at + UA_AFTER_GAME_START + 24]) \
                        if at + UA_AFTER_GAME_START + 24 <= len(buf) else None
                    if ua is None:
                        raw = reader.read(base + offset + at + UA_AFTER_GAME_START, 24)
                        ua = ua_from_bytes(raw) if raw and len(raw) == 24 else None
                    if ua is not None:
                        player_states.append(base + offset + at)
                    at = buf.find(anchor, at + 1)
            for row in candidate_rows(buf):
                if row >= length:
                    break
                start = row - P_COMMON
                if start >= 0 and start + PLANET_SIZE <= len(buf):
                    blob = buf[start:start + PLANET_SIZE]
                else:
                    blob = reader.read(base + offset + start, PLANET_SIZE)
                    if not blob:
                        continue
                planet = parse_planet(blob, reader.read, substances)
                if planet:
                    # By address and name: a reused slot can carry another planet's address (history.planet_id).
                    planets[(planet["ua"], planet["name"])] = planet
    return ScanResult(sorted(planets.values(), key=lambda p: (p["system"], p["index"])), player_states, total,
                      round(clock() - started, 2))


def read_current_address(reader, player_state: int) -> dict | None:
    """The player's current universe address, read at the remembered player-state anchor."""
    raw = reader.read(player_state + UA_AFTER_GAME_START, 24)
    return ua_from_bytes(raw) if raw and len(raw) == 24 else None


def find_game_pid() -> int | None:
    """PID of NMS.exe, or None when the game is not running."""
    try:
        import psutil
    except ImportError as exc:  # pragma: no cover - the host ships psutil
        raise MemoryUnavailable("finding the game process needs psutil (part of the 40k Assistant)") from exc
    for proc in psutil.process_iter(["name"]):
        if (proc.info.get("name") or "").lower() == GAME_EXE:
            return proc.pid
    return None
