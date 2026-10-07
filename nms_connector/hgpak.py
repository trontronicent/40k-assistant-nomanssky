"""Read files out of the game's HGPAK archives (GAMEDATA/PCBANKS/*.pak). Read-only.

Format (version 2, since the Worlds update; documented by monkeyman192's
HGPAKtool, MIT):

- Header, 0x30 bytes: ``b"HGPAK"`` padded to 8, then ``<version u64, file
  count u64, chunk count u64, is_compressed u8 + 7 pad, data offset u64>``.
- File index: one ``<md5 of the path 16s, offset u64, size u64>`` per file.
  Entry 0 is the manifest: the file paths, CRLF-separated, in index order
  (entry ``i + 1`` belongs to path ``i``).
- Chunk index (compressed paks): one compressed size u64 per chunk. Chunks
  start at the data offset, each padded to 16 bytes, and decompress to 64 KiB.
  Offsets in the file index count in that decompressed stream (plus the data
  offset). On Windows and Linux chunks are zstd frames; a chunk whose stored
  size is exactly 64 KiB is stored uncompressed.

zstd is not in Python's standard library before 3.14; the 40k Assistant ships
the ``zstandard`` package from version 3.1.0. Without it ``ZstdUnavailable`` is
raised and the plugin explains that names and icons need it.
"""

from __future__ import annotations

import struct
import threading
from contextlib import contextmanager
from pathlib import Path

from . import logs

try:  # Python 3.14+
    from compression import zstd as _stdlib_zstd  # type: ignore[import-not-found]
except ImportError:
    _stdlib_zstd = None
try:
    import zstandard as _zstandard  # type: ignore[import-not-found]
except ImportError:
    _zstandard = None

# The paks that hold the tables the plugin reads (checked 2026-10-08 on build 25732212 by scanning every pak). A wrong
# hint costs a scan that opens up to 21 paks - each open builds the file index (up to ~29 MB, 0.4 s) - so these matter.
TABLE_PAK = "NMSARC.Precache.pak"            # metadata/reality/tables/*.mbin
GLOBALS_PAK = "NMSARC.globals.pak"           # gc*globals.mbin
LANGUAGE_PAK = "NMSARC.MetadataEtc.pak"      # language/*.mbin
UI_TEXTURE_PAK = "NMSARC.TexUI.pak"          # textures/ui/*
TABLE_DIR = "metadata/reality/tables/"
PAK_HINTS = {TABLE_DIR: TABLE_PAK, "language/": LANGUAGE_PAK, "textures/ui/": UI_TEXTURE_PAK}   # path prefix -> its pak
SCAN_WARN_OPENS = 3          # a file found only after opening this many paks means a stale hint (logged)

MAGIC = b"HGPAK"
FORMAT_VERSION = 2
CHUNK_SIZE = 0x10000
HEADER = struct.Struct("<QQQ?7xQ")
ENTRY = struct.Struct("<16sQQ")


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


class PakError(ValueError):
    """Not a readable HGPAK file, or a file inside it is damaged."""


class ZstdUnavailable(RuntimeError):
    """No zstd decompressor is installed (needs the zstandard package or Python 3.14)."""


def zstd_available() -> bool:
    return _zstandard is not None or _stdlib_zstd is not None


def _decompressor():
    if _zstandard is not None:
        dctx = _zstandard.ZstdDecompressor()
        return lambda data: dctx.decompress(data, max_output_size=CHUNK_SIZE)
    if _stdlib_zstd is not None:
        return _stdlib_zstd.decompress
    raise ZstdUnavailable("reading the game's archives needs the Python package 'zstandard'")


class Pak:
    """One open .pak file; use as a context manager."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._f = open(self.path, "rb")
        self._lock = threading.RLock()          # a shared pak (see `session`) may be read by two threads
        try:
            self._read_index()
        except Exception:
            self._f.close()
            raise

    def __enter__(self) -> Pak:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._f.close()
        self.names = {}                     # the index is the pak's memory: let it go with the file
        self._index = b""

    def _read_index(self) -> None:
        """Read the header, the file index and (compressed paks) the chunk index; PakError when malformed."""
        head = self._f.read(0x30)
        if len(head) < 0x30 or head[:5] != MAGIC:
            raise PakError(f"{self.path.name} is not an HGPAK file")
        version, files, chunks, compressed, data_offset = HEADER.unpack(head[8:0x30])
        if version != FORMAT_VERSION:
            raise PakError(f"{self.path.name}: HGPAK version {version} is not supported (expected {FORMAT_VERSION})")
        if not files:
            raise PakError(f"{self.path.name} has no files")
        size = self.path.stat().st_size
        index = self._f.read(ENTRY.size * files)
        if len(index) != ENTRY.size * files:
            raise PakError(f"{self.path.name}: file index is truncated")
        # The raw index stays as bytes and entries are unpacked on demand: a Python tuple per file cost ~100 bytes of
        # the ~400 per file an open pak held (50,000 files in MetadataEtc).
        self._index = index
        self._files = files
        self.compressed = bool(compressed)
        self._data_offset = data_offset
        self._chunk_sizes: tuple[int, ...] = ()
        self._chunk_offsets: list[int] = []
        if self.compressed:
            raw = self._f.read(8 * chunks)
            if len(raw) != 8 * chunks:
                raise PakError(f"{self.path.name}: chunk index is truncated")
            self._chunk_sizes = struct.unpack(f"<{chunks}Q", raw)
            pos = data_offset
            for chunk in self._chunk_sizes:
                self._chunk_offsets.append(pos)
                pos += (chunk + 15) & ~15
            if pos > size + 16:
                raise PakError(f"{self.path.name}: chunks run past the end of the file")
            self._decompress = _decompressor()
        self._cached_chunk = (-1, b"")
        manifest = self._read_entry(0).rstrip(b"\r\n").decode("utf-8", "replace").lower().split("\r\n")
        self.names = {name: i + 1 for i, name in enumerate(manifest) if name}
        del manifest

    def _chunk(self, index: int) -> bytes:
        """One 64 KiB chunk, decompressed (a stored size of exactly 64 KiB is raw); the last one is cached."""
        if self._cached_chunk[0] == index:
            return self._cached_chunk[1]
        if index >= len(self._chunk_sizes):
            raise PakError(f"{self.path.name}: chunk {index} does not exist")
        self._f.seek(self._chunk_offsets[index])
        stored = self._chunk_sizes[index]
        data = self._f.read(stored)
        if stored != CHUNK_SIZE:
            try:
                data = self._decompress(data)
            except Exception as exc:  # zstd raises its own error types
                raise PakError(f"{self.path.name}: chunk {index} does not decompress ({exc})") from exc
        self._cached_chunk = (index, data)
        return data

    def _read_entry(self, k: int) -> bytes:
        """The bytes of file entry k: read directly, or assembled from the chunks it spans."""
        if not 0 <= k < self._files:
            raise PakError(f"{self.path.name}: entry {k} does not exist")
        _, offset, size = ENTRY.unpack_from(self._index, k * ENTRY.size)
        if not self.compressed:
            self._f.seek(offset)
            data = self._f.read(size)
            if len(data) != size:
                raise PakError(f"{self.path.name}: entry {k} is truncated")
            return data
        offset -= self._data_offset
        if offset < 0:
            raise PakError(f"{self.path.name}: entry {k} has a bad offset")
        out = bytearray()
        chunk, skip = divmod(offset, CHUNK_SIZE)
        while len(out) < size:
            data = self._chunk(chunk)
            if not data or len(data) <= skip:
                raise PakError(f"{self.path.name}: entry {k} is truncated")
            out += data[skip:]
            skip = 0
            chunk += 1
        return bytes(out[:size])

    def read(self, name: str) -> bytes:
        """The file's bytes; KeyError when this pak does not contain it."""
        with self._lock:
            return self._read_entry(self.names[name.lower()])


class _SessionState:
    """The shared paks of the active `session` (None outside one) and how many sessions are nested."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.paks: dict[str, Pak] | None = None      # path -> open Pak
        self.depth = 0


_SESSION = _SessionState()


def session_active() -> bool:
    """True inside a `session()` block."""
    return _SESSION.paks is not None


@contextmanager
def session():
    """Share the opened paks between every PakSet created inside the block, and free them all at its end.

    Reading the game's tables opens the same few paks again and again (each open builds the file index, up to 29 MB
    and 0.4 s for MetadataEtc); inside one load pass they are opened once. Nothing stays open or in memory after
    the block - the plugin must not hold ~20 MB of file names between reads. Re-entrant (the outermost block frees)."""
    with _SESSION.lock:
        if _SESSION.paks is None:
            _SESSION.paks = {}
        _SESSION.depth += 1
    try:
        yield
    finally:
        with _SESSION.lock:
            _SESSION.depth -= 1
            if _SESSION.depth == 0:
                paks, _SESSION.paks = _SESSION.paks, None
                for pak in paks.values():
                    pak.close()


class PakSet:
    """All paks of one installation; finds a file in whichever pak holds it.

    ``hints`` maps a path prefix to the pak that usually holds it, so the common
    files are found without opening every pak. Paks are opened on demand and
    closed by ``close()`` (use as a context manager), so the game's files are
    never held open between reads.
    """

    def __init__(self, pcbanks: Path, hints: dict[str, str] | None = None):
        self.pcbanks = Path(pcbanks)
        self.hints = hints or {}
        self._open: dict[str, Pak] = {}         # the paks this set opened itself (a session's are not its to close)
        self._paths = sorted(self.pcbanks.glob("*.pak"), key=lambda p: p.name.lower())
        if not self._paths:
            raise PakError(f"no .pak files in {self.pcbanks}")
        # Where nothing is hinted, the small paks (metadata, globals) are tried before the big texture and audio
        # ones, whose indexes are the expensive ones to build.
        self._by_size = sorted(self._paths, key=lambda p: (_size(p), p.name.lower()))

    def __enter__(self) -> PakSet:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        for pak in self._open.values():
            pak.close()
        self._open.clear()

    def _pak(self, path: Path) -> Pak:
        with _SESSION.lock:
            if _SESSION.paks is not None:
                if str(path) not in _SESSION.paks:
                    _SESSION.paks[str(path)] = Pak(path)
                return _SESSION.paks[str(path)]
        if path.name not in self._open:
            self._open[path.name] = Pak(path)
        return self._open[path.name]

    def _order(self, name: str) -> list[Path]:
        preferred = [hint for prefix, hint in self.hints.items() if name.startswith(prefix)]
        first = [p for p in self._paths if p.name in preferred]
        return first + [p for p in self._by_size if p.name not in preferred]

    def find(self, name: str) -> Pak | None:
        name = name.lower()
        for opened, path in enumerate(self._order(name), start=1):
            pak = self._pak(path)
            if name in pak.names:
                if opened >= SCAN_WARN_OPENS:
                    logs.warn_once(f"pakscan:{name}", "%s was found in %s only after opening %d paks - its pak hint "
                                   "is stale (slow and memory-hungry); update the hint in the plugin", name, path.name, opened)
                return pak
        return None

    def read(self, name: str) -> bytes:
        pak = self.find(name)
        if pak is None:
            raise KeyError(name)
        return pak.read(name)

    def names_matching(self, prefix: str, suffix: str) -> list[str]:
        """Every path starting with prefix and ending with suffix, in the hinted pak(s) first, else all."""
        prefix, suffix = prefix.lower(), suffix.lower()
        found: list[str] = []
        for path in self._order(prefix):
            names = [n for n in self._pak(path).names if n.startswith(prefix) and n.endswith(suffix)]
            if names:
                found += [n for n in names if n not in found]
                if path.name in self.hints.values():
                    break
        return sorted(found)
