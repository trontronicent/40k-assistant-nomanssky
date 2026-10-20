"""The savegame editor's write path: the LZ4 encoder and the byte-faithful save round trip.

The editor is the plugin's only code that writes a save, so these tests are the proof that what it writes
decodes back to exactly what it meant. `saves.py` stays read-only; `save_write.py` is the write side.
"""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest

from nms_connector.lz4 import compress_block, decompress_block
from nms_connector.save_write import CHUNK, RawSave, decode_lossless, encode_bytes, read_raw, write_save
from nms_connector.saves import MAGIC, SaveFormatError


@pytest.mark.parametrize("size", [0, 1, 14, 15, 16, 254, 269, 270, 271, 70000])
def test_compress_block_round_trips_at_every_length_boundary(size):
    """`compress_block` output must decode back to the input for the lengths where LZ4's token and its
    extended-length bytes change shape (<15, ==15, each 255 step). A length bug here corrupts a save."""
    data = bytes((i * 7 + 3) % 256 for i in range(size))

    encoded = compress_block(data)

    assert decompress_block(encoded, size) == data


def test_compress_block_emits_a_literals_only_block():
    """The encoder must emit literals only - no match sequences - because a literals-only block is correct by
    construction and needs no match finding. The token's match nibble is therefore always 0."""
    encoded = compress_block(b"abcabcabcabc")

    assert encoded[0] & 0x0F == 0
    assert encoded.endswith(b"abcabcabcabc")


# A save whose strings include bytes that are not valid UTF-8, as the real game's saves do (623 such bytes in
# the developer's save3.hg on 2026-10-20). `saves.decode_bytes` replaces them; the editor must not.
RAW_JSON = b'{"F2P":4740,"NM1":"caf\xe9 \xff\xfe","INV":{"SLT":[{"ID1":"^FUEL1","AM1":50}]}}'


def game_file_bytes(payload: bytes, chunk: int = CHUNK) -> bytes:
    """Wrap `payload` in FEEDA1E5 chunks the way the game writes them, with its trailing NUL."""
    body = payload + b"\x00"
    out = bytearray()
    for i in range(0, len(body), chunk):
        part = body[i:i + chunk]
        block = compress_block(part)
        out += struct.pack("<IIII", MAGIC, len(block), len(part), 0) + block
    return bytes(out)


def test_read_raw_then_encode_reproduces_the_file_byte_for_byte(tmp_path):
    """A no-op round trip must give back exactly the bytes that were read, including the strings that are not
    UTF-8 and the trailing NUL. This is the single most important property of the write path: if it does not
    hold, every edit silently damages parts of the save it never touched."""
    path = tmp_path / "save.hg"
    path.write_bytes(game_file_bytes(RAW_JSON))

    raw = read_raw(path)

    assert encode_bytes(raw) == path.read_bytes()


def test_read_raw_keeps_the_non_utf8_strings_recoverable(tmp_path):
    """The editor decodes with surrogateescape, not `replace`, so the odd bytes survive as surrogates and
    encode back to themselves. `saves.decode_bytes` would turn them into U+FFFD and lose them for good."""
    path = tmp_path / "save.hg"
    path.write_bytes(game_file_bytes(RAW_JSON))

    raw = read_raw(path)

    assert "�" not in raw.text
    assert raw.text.encode("utf-8", "surrogateescape") == RAW_JSON


def test_read_raw_exposes_the_obfuscated_tree_untranslated(tmp_path):
    """The editor works on the raw tree and never re-obfuscates, because `saves.deobfuscate` is not
    invertible. So `read_raw` must hand back the obfuscated keys exactly as the file has them."""
    path = tmp_path / "save.hg"
    path.write_bytes(game_file_bytes(RAW_JSON))

    raw = read_raw(path)

    assert raw.tree["F2P"] == 4740
    assert raw.tree["INV"]["SLT"][0]["ID1"] == "^FUEL1"


def test_with_tree_reserialises_an_edited_tree_and_survives_the_round_trip(tmp_path):
    """An edit replaces the tree; `with_tree` must produce text that encodes and decodes back to that tree,
    keeping the non-UTF-8 strings intact. This is the path every real edit takes."""
    path = tmp_path / "save.hg"
    path.write_bytes(game_file_bytes(RAW_JSON))
    raw = read_raw(path)
    tree = json.loads(json.dumps(raw.tree))
    tree["INV"]["SLT"][0]["AM1"] = 9999

    edited = raw.with_tree(tree)
    written = tmp_path / "out.hg"
    write_save(written, edited)

    assert read_raw(written).tree == tree
    assert read_raw(written).text.encode("utf-8", "surrogateescape").count(b"caf\xe9 \xff\xfe") == 1


def test_encode_bytes_never_exceeds_the_games_chunk_size(tmp_path):
    """The game reads a sequence of chunks of at most 512 kB; a larger one is not something it is known to
    accept. A multi-chunk save must therefore be split exactly as the game splits it."""
    payload = b'{"A":"' + b"x" * (CHUNK * 2) + b'"}'
    path = tmp_path / "save.hg"
    path.write_bytes(game_file_bytes(payload))

    data = encode_bytes(read_raw(path))

    pos, usizes = 0, []
    while pos < len(data):
        magic, csize, usize, _ = struct.unpack_from("<IIII", data, pos)
        assert magic == MAGIC
        usizes.append(usize)
        pos += 16 + csize
    assert max(usizes) <= CHUNK
    assert sum(usizes) == len(payload) + 1


def test_write_save_replaces_atomically_and_leaves_no_temp_file(tmp_path):
    """A half-written save is a destroyed save, so the write goes to a temp file and is moved into place.
    Nothing may be left behind in the game's own folder."""
    path = tmp_path / "save.hg"
    path.write_bytes(game_file_bytes(RAW_JSON))
    raw = read_raw(path)

    write_save(path, raw)

    assert encode_bytes(raw) == path.read_bytes()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["save.hg"]


def test_read_raw_refuses_a_file_that_is_not_a_save(tmp_path):
    """A truncated or foreign file must be refused with the format error the read path already uses, not
    silently treated as an empty save that an edit would then write over the real one."""
    path = tmp_path / "save.hg"
    path.write_bytes(b"not a save at all")

    with pytest.raises(SaveFormatError):
        read_raw(path)


REAL_SAVE_DIR = os.environ.get("NMS_SAVE_DIR")


@pytest.mark.skipif(not REAL_SAVE_DIR, reason="NMS_SAVE_DIR not set: no real saves to round trip")
def test_real_saves_round_trip_their_payload_exactly():
    """The correctness gate from the design: every real save on this machine must survive a no-op round trip
    with its decoded payload - JSON text and trailing padding - unchanged. Fixtures cannot prove this; only
    the game's own multi-megabyte, multi-chunk files, with the strings that are not UTF-8, can.

    The *file* bytes differ by design: the game's blocks carry LZ4 matches and `compress_block` writes literals
    only, so the re-encoded file is larger. What the game reads back is identical, which is the property that
    matters."""
    saves = sorted(Path(REAL_SAVE_DIR).glob("save*.hg"))
    assert saves, f"no save*.hg in {REAL_SAVE_DIR}"

    for path in saves:
        original = path.read_bytes()
        assert decode_lossless(encode_bytes(read_raw(path))) == decode_lossless(original), path.name


def test_raw_save_is_immutable():
    """`RawSave` is passed around the commit pipeline and must not be edited in place - `with_tree` returns a
    new one, so a validation failure can never leave a half-changed save in memory."""
    raw = RawSave(text='{"A":1}', tail=b"\x00")

    with pytest.raises((AttributeError, TypeError)):
        raw.text = '{"A":2}'
