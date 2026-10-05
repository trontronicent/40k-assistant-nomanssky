"""Find, read and de-obfuscate No Man's Sky save files. Read-only, always.

Format (since the Waypoint update): a sequence of chunks, each a 16-byte header
``<magic 0xFEEDA1E5, compressed size, uncompressed size, padding>`` (little
endian) followed by an LZ4 block of at most 512 kB. The concatenated output is
JSON whose keys are obfuscated three-character codes (``"F2P"``); the mapping to
real names ships as ``mapping.json`` with every MBINCompiler release.

Save files per slot: ``save.hg`` + ``save2.hg`` are slot 1, ``save3.hg`` +
``save4.hg`` slot 2, and so on. ``mf_*.hg`` files are small metadata companions.
"""

from __future__ import annotations

import json
import os
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from .lz4 import decompress_block

MAGIC = 0xFEEDA1E5
SAVE_RE = re.compile(r"^save(\d*)\.hg$", re.IGNORECASE)
STEAM_APP_ID = "275850"


class SaveFormatError(ValueError):
    """The file is not a save in the expected format (or was read mid-write)."""


@dataclass(frozen=True)
class SaveFile:
    """One save file on disk: its number (save.hg = 1, save2.hg = 2, ...), size and modification time."""
    path: Path
    number: int          # 1 for save.hg, 2 for save2.hg, ...
    size: int
    mtime: float

    @property
    def slot(self) -> int:
        return (self.number + 1) // 2


def save_file_number(name: str) -> int | None:
    m = SAVE_RE.match(name)
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else 1


def candidate_save_roots() -> list[Path]:
    """Where the game keeps saves on this machine (override with NMS_SAVE_DIR)."""
    override = os.environ.get("NMS_SAVE_DIR")
    if override:
        return [Path(override)]
    roots: list[Path] = []
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            roots.append(Path(appdata) / "HelloGames" / "NMS")
    else:
        home = Path.home()
        for steam in (home / ".steam" / "steam", home / ".local" / "share" / "Steam"):
            roots.append(steam / "steamapps" / "compatdata" / STEAM_APP_ID / "pfx" / "drive_c" / "users"
                         / "steamuser" / "AppData" / "Roaming" / "HelloGames" / "NMS")
    return roots


def find_save_dirs(roots: list[Path] | None = None) -> list[Path]:
    """Account folders that contain saves (Steam: st_<id>, GOG: DefaultUser), newest first."""
    found = []
    for root in roots if roots is not None else candidate_save_roots():
        if not root.is_dir():
            continue
        dirs = [root] + [d for d in root.iterdir() if d.is_dir()]
        for d in dirs:
            saves = list_save_files(d)
            if saves:
                found.append((max(s.mtime for s in saves), d))
    return [d for _, d in sorted(found, reverse=True)]


def list_save_files(folder: Path) -> list[SaveFile]:
    """Every save*.hg in a folder, by number; [] when the folder cannot be read."""
    out = []
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return out
    for entry in entries:
        number = save_file_number(entry.name)
        if number is None or not entry.is_file():
            continue
        st = entry.stat()
        out.append(SaveFile(Path(entry.path), number, st.st_size, st.st_mtime))
    return sorted(out, key=lambda s: s.number)


def decode_bytes(data: bytes) -> str:
    """Decompress a save file's bytes into its JSON text."""
    pos, out = 0, bytearray()
    if len(data) < 16:
        raise SaveFormatError("file too short")
    while pos < len(data):
        if pos + 16 > len(data):
            raise SaveFormatError("truncated chunk header (file read while being written?)")
        magic, csize, usize, _ = struct.unpack_from("<IIII", data, pos)
        if magic != MAGIC:
            raise SaveFormatError(f"unexpected chunk magic {magic:#x} at byte {pos}")
        pos += 16
        if pos + csize > len(data):
            raise SaveFormatError("truncated chunk (file read while being written?)")
        try:
            out += decompress_block(data[pos:pos + csize], usize)
        except ValueError as exc:
            raise SaveFormatError(f"corrupt chunk at byte {pos}: {exc}") from exc
        pos += csize
    # A few strings hold raw bytes that are not UTF-8; replacing them is harmless here.
    return out.rstrip(b"\x00").decode("utf-8", errors="replace")


def load_mapping(path: Path) -> dict[str, str]:
    """Read MBINCompiler's mapping.json into {obfuscated: readable}."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {e["Key"]: e["Value"] for e in raw["Mapping"]}


def deobfuscate(obj, mapping: dict[str, str], unknown: set[str]):
    """Rename every key; collect keys the mapping does not know."""
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            name = mapping.get(key)
            if name is None:
                unknown.add(key)
                name = key
            out[name] = deobfuscate(value, mapping, unknown)
        return out
    if isinstance(obj, list):
        return [deobfuscate(v, mapping, unknown) for v in obj]
    return obj


def read_save(path: Path, mapping: dict[str, str]) -> tuple[dict, set[str]]:
    """Read one save (read-only) and return (readable dict, unknown keys)."""
    with open(path, "rb") as fh:
        data = fh.read()
    try:
        raw = json.loads(decode_bytes(data))
    except json.JSONDecodeError as exc:
        raise SaveFormatError(f"not valid JSON after decompression: {exc}") from exc
    unknown: set[str] = set()
    return deobfuscate(raw, mapping, unknown), unknown
