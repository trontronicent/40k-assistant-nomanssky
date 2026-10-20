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

from nms_connector.lz4 import LAST_LITERALS, MIN_MATCH, compress_block, decompress_block
from nms_connector.save_write import CHUNK, RawSave, decode_lossless, encode_bytes, read_raw, write_save
from nms_connector.saves import MAGIC, SaveFormatError


@pytest.mark.parametrize("size", [0, 1, 14, 15, 16, 254, 269, 270, 271, 70000])
def test_compress_block_round_trips_at_every_length_boundary(size):
    """`compress_block` output must decode back to the input for the lengths where LZ4's token and its
    extended-length bytes change shape (<15, ==15, each 255 step). A length bug here corrupts a save."""
    data = bytes((i * 7 + 3) % 256 for i in range(size))

    encoded = compress_block(data)

    assert decompress_block(encoded, size) == data


def test_compress_block_actually_compresses_repetitive_data():
    """The encoder must find matches, not just emit literals: a literals-only save is about four times the
    size of the game's own (measured 1.4 MB -> 5.5 MB), which is a real regression for the player's disk and
    their Steam Cloud quota."""
    data = b"abcdefgh" * 2000

    encoded = compress_block(data)

    assert len(encoded) < len(data) // 4
    assert decompress_block(encoded, len(data)) == data


def test_compress_block_keeps_the_last_bytes_as_literals():
    """The LZ4 block format requires the last sequence to be literals and forbids a match in the final 12
    bytes. Our own decompressor is lenient, but the game's is real LZ4 - a block that breaks the rule may
    decode here and be rejected by the game, which is the worst possible failure mode."""
    data = b"abcdefgh" * 2000

    encoded = compress_block(data)

    assert encoded.endswith(data[-5:])


def strict_block_problem(block: bytes, out_size: int) -> str | None:
    """Why `block` breaks the LZ4 block format, or None. An independent, strict reader.

    `decompress_block` is deliberately lenient - it is the save *reader* and takes what the game gives it. The
    game's own decompressor is real LZ4 and may reject what ours accepts, so the encoder's output is checked
    against the format's rules here instead: a 4-byte minimum match, an offset that stays inside the output,
    the last five bytes literal, and no match beginning in the final twelve.
    """
    pos, produced, last_match_end = 0, 0, None
    while pos < len(block):
        token = block[pos]
        pos += 1
        literals = token >> 4
        if literals == 15:
            while block[pos] == 255:
                literals += 255
                pos += 1
            literals += block[pos]
            pos += 1
        produced += literals
        pos += literals
        if pos >= len(block):
            if literals < LAST_LITERALS and out_size >= LAST_LITERALS:
                return f"final literal run is {literals} bytes, the format needs at least {LAST_LITERALS}"
            break
        offset = block[pos] | (block[pos + 1] << 8)
        pos += 2
        match = (token & 15) + MIN_MATCH
        if (token & 15) == 15:
            while block[pos] == 255:
                match += 255
                pos += 1
            match += block[pos]
            pos += 1
        if offset == 0 or offset > produced:
            return f"match offset {offset} reaches outside the {produced} bytes produced so far"
        if match < MIN_MATCH:
            return f"match length {match} is below the minimum {MIN_MATCH}"
        produced += match
        last_match_end = produced
    if produced != out_size:
        return f"produced {produced} bytes, expected {out_size}"
    if last_match_end is not None and out_size - last_match_end < LAST_LITERALS:
        return f"a match ends {out_size - last_match_end} bytes from the end; the last {LAST_LITERALS} must be literals"
    return None


def test_the_strict_validator_rejects_a_block_that_breaks_the_end_rule():
    """The validator is only worth something if it bites. A hand-built block whose match runs to the very end
    decodes fine through our lenient reader and must still be reported as malformed."""
    block = bytes([0x40]) + b"abcd" + (1).to_bytes(2, "little")      # 4 literals, then a match of 4 at offset 1

    assert decompress_block(block, 8) == b"abcddddd"
    assert strict_block_problem(block, 8) is not None


@pytest.mark.parametrize("data", [
    pytest.param(b"", id="empty"),
    pytest.param(b"a", id="one-byte"),
    pytest.param(b"abcd", id="exactly-min-match"),
    pytest.param(b"a" * 32, id="overlapping-match"),
    pytest.param(b"abcd" * 5 + b"zzzz" + b"abcd" * 5, id="match-literals-match"),
    pytest.param(bytes(range(256)) * 300, id="match-longer-than-one-token"),
    pytest.param(b"x" * 70000 + b"y" * 70000, id="extended-lengths"),
])
def test_compress_block_round_trips_every_sequence_shape(data):
    """Each input exercises a different corner of the encoder - overlapping matches, alternating literal and
    match runs, lengths that need the 255 continuation bytes. A save is only as safe as these corners."""
    encoded = compress_block(data)

    assert decompress_block(encoded, len(data)) == data
    assert strict_block_problem(encoded, len(data)) is None


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
