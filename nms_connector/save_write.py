"""Write a No Man's Sky save file. The only module in the plugin that does; everything else reads.

`saves.py` stays read-only, as its docstring promises, because its read path cannot be reversed:

* `saves.decode_bytes` decodes with ``errors="replace"``, and a real save genuinely holds strings that are not
  UTF-8 (623 such bytes in one of the developer's saves). Decoding them to U+FFFD loses them for good, so this
  module decodes with ``surrogateescape`` instead and encodes back the same way.
* `saves.deobfuscate` is not invertible: a key the mapping does not know keeps its obfuscated name, and nothing
  guarantees that the mapping's readable names are unique. So the editor works on the **raw, obfuscated tree**
  and never re-obfuscates. `mapping.json` is used in one direction only, to find an obfuscated key by name.

The format is the one `saves.decode_bytes` reads: chunks of a 16-byte header
``<magic 0xFEEDA1E5, compressed size, uncompressed size, padding>`` followed by an LZ4 block of at most 512 kB,
and the concatenated JSON ends with a NUL. A no-op round trip through this module reproduces the file byte for
byte - `tests/test_save_write.py` holds that to the real saves as well as to fixtures.
"""

from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass, replace
from pathlib import Path

from .lz4 import LZ4Error, compress_block, decompress_block
from .saves import MAGIC, SaveFormatError

CHUNK = 512 * 1024      # the game's uncompressed chunk size; the last chunk is the remainder


@dataclass(frozen=True)
class RawSave:
    """One save's JSON text (surrogateescape-decoded, obfuscated keys) and the trailing NUL padding.

    Frozen: the commit pipeline passes it around, and `with_tree` returns a new one, so a validation failure
    can never leave a half-changed save behind in memory.
    """
    text: str
    tail: bytes

    @property
    def tree(self) -> dict:
        """The parsed obfuscated tree. Parsed on demand; the text is what gets written."""
        return json.loads(self.text)

    def with_tree(self, tree: dict) -> RawSave:
        """A copy whose text is `tree` re-serialised the way the game writes it: compact, no ASCII escaping."""
        return replace(self, text=json.dumps(tree, separators=(",", ":"), ensure_ascii=False))


def _chunks(data: bytes) -> list[bytes]:
    """`data` split into the game's 512 kB pieces (one empty piece for empty input, as the game never writes)."""
    return [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [b""]


def decode_lossless(data: bytes) -> tuple[str, bytes]:
    """(JSON text, trailing NUL padding) from a save file's bytes, losing nothing.

    The same chunk walk as `saves.decode_bytes`, but the text keeps the bytes that are not UTF-8 as surrogates
    and the stripped padding is handed back so the writer can restore it exactly.
    """
    if len(data) < 16:
        raise SaveFormatError("file too short")
    pos, out = 0, bytearray()
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
        except LZ4Error as exc:
            raise SaveFormatError(f"corrupt chunk at byte {pos}: {exc}") from exc
        pos += csize
    body = bytes(out)
    stripped = body.rstrip(b"\x00")
    return stripped.decode("utf-8", errors="surrogateescape"), body[len(stripped):]


def read_raw(path: Path | str) -> RawSave:
    """Read one save losslessly. `SaveFormatError` when it is not a save in the expected format."""
    data = Path(path).read_bytes()
    text, tail = decode_lossless(data)
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        raise SaveFormatError(f"not valid JSON after decompression: {exc}") from exc
    return RawSave(text=text, tail=tail)


def encode_bytes(raw: RawSave) -> bytes:
    """`raw` as the bytes of a save file: the game's chunk headers around literals-only LZ4 blocks."""
    body = raw.text.encode("utf-8", errors="surrogateescape") + raw.tail
    out = bytearray()
    for part in _chunks(body):
        block = compress_block(part)
        out += struct.pack("<IIII", MAGIC, len(block), len(part), 0) + block
    return bytes(out)


def write_save(path: Path | str, raw: RawSave) -> None:
    """Write `raw` to `path` atomically: a temp file beside it, then a replace.

    A half-written save is a destroyed save, and the game may read the file at any moment, so the real name
    only ever points at a complete file. The temp file is removed on failure, leaving the game's folder clean.
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".nms-editor.tmp")
    try:
        tmp.write_bytes(encode_bytes(raw))
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
