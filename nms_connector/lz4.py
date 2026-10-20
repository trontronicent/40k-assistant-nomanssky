"""LZ4 block decompression (pure Python, no dependency).

No Man's Sky compresses its save files in LZ4 *blocks* (not the LZ4 frame
format). A 3 MB save decodes in well under a second, which is plenty for a file
the game writes every few minutes.
"""


class LZ4Error(ValueError):
    """The input is not a valid LZ4 block."""


def _extended_length(src: bytes, i: int, base: int, what: str) -> tuple[int, int]:
    """(length, next position): `base` (the token's 15) plus the extra bytes that follow it, each added until one is
    not 255. Used for both the literal run and the match length."""
    n = len(src)
    length = base
    while True:
        if i >= n:
            raise LZ4Error(f"truncated {what} length")
        extra = src[i]
        i += 1
        length += extra
        if extra != 255:
            return length, i


def _copy_match(dst: bytearray, offset: int, length: int) -> None:
    """Append `length` bytes copied from `offset` bytes back; an overlapping copy repeats the last `offset` bytes.
    LZ4Error for an offset of 0 or one reaching before the output."""
    if offset == 0 or offset > len(dst):
        raise LZ4Error("invalid match offset")
    start = len(dst) - offset
    if length <= offset:
        dst += dst[start:start + length]
    else:
        for k in range(length):
            dst.append(dst[start + k])


def decompress_block(src: bytes, out_size: int) -> bytes:
    """Decompress one LZ4 block whose uncompressed size is known.

    The loop is the save decoder's hot path: no helper call is added per sequence (one cost 5-10 %, measured
    2026-10-18 on 200,000 sequences), so the offset is checked inside `_copy_match`, which runs anyway."""
    dst = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        literals = token >> 4
        if literals == 15:
            literals, i = _extended_length(src, i, literals, "literal")
        if i + literals > n:
            raise LZ4Error("literals run past the end of the block")
        dst += src[i:i + literals]
        i += literals
        if i >= n:
            break  # the last sequence has literals only
        if i + 2 > n:
            raise LZ4Error("truncated match offset")
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        length = token & 15
        if length == 15:
            length, i = _extended_length(src, i, length, "match")
        _copy_match(dst, offset, length + 4)
    if len(dst) != out_size:
        raise LZ4Error(f"decoded {len(dst)} bytes, expected {out_size}")
    return bytes(dst)


MIN_MATCH = 4           # LZ4's shortest match; a match length is stored as length - 4
MAX_OFFSET = 0xFFFF     # the offset is two bytes
LAST_LITERALS = 5       # the block's last 5 bytes must be literals
MF_LIMIT = 12           # and no match may start within the last 12


def _emit_length(out: bytearray, rest: int) -> None:
    """The continuation bytes for a length that did not fit in its 4-bit nibble: 255 until the remainder."""
    while rest >= 255:
        out.append(255)
        rest -= 255
    out.append(rest)


def _emit_literals(out: bytearray, data: bytes) -> None:
    """A final, match-less sequence: the token (match nibble 0), the literal length bytes, the literals.

    A sequence without a match carries no offset, which is why this is only ever the block's last one.
    """
    n = len(data)
    out.append(min(n, 15) << 4)
    if n >= 15:
        _emit_length(out, n - 15)
    out += data


def _emit_sequence(out: bytearray, literals: bytes, offset: int, match_len: int) -> None:
    """One full sequence: token, literal length, the literals, the 2-byte offset, the match length."""
    extra = match_len - MIN_MATCH
    out.append((min(len(literals), 15) << 4) | min(extra, 15))
    if len(literals) >= 15:
        _emit_length(out, len(literals) - 15)
    out += literals
    out += offset.to_bytes(2, "little")
    if extra >= 15:
        _emit_length(out, extra - 15)


def _match_end(data: bytes, pos: int, cand: int, limit: int) -> int:
    """How far the match at `cand` extends the one at `pos`, stopping at `limit` (the last-literals boundary)."""
    end, other = pos + MIN_MATCH, cand + MIN_MATCH
    while end < limit and data[end] == data[other]:
        end += 1
        other += 1
    return end


def compress_block(data: bytes) -> bytes:
    """Encode `data` as one LZ4 block - the encoder the savegame editor writes saves with.

    A greedy single-candidate matcher over a hash table of 4-byte sequences: good enough to bring a save back
    to roughly the size the game writes (a literals-only encoding turned a 1.4 MB save into 5.5 MB), and small
    enough to read in one sitting. The format's end rules are honoured, because the *game's* decompressor is
    real LZ4 and is entitled to reject a block that this module's lenient `decompress_block` would accept: the
    last sequence is literals only, and no match starts in the final `MF_LIMIT` bytes.
    """
    n = len(data)
    out = bytearray()
    if n < MF_LIMIT + MIN_MATCH:
        _emit_literals(out, data)           # too short for any match to be legal
        return bytes(out)
    table: dict[bytes, int] = {}
    extend_limit, start_limit = n - LAST_LITERALS, n - MF_LIMIT
    anchor = pos = 0
    while pos < start_limit:
        key = data[pos:pos + MIN_MATCH]
        cand = table.get(key, -1)
        table[key] = pos
        if cand < 0 or pos - cand > MAX_OFFSET:
            pos += 1
            continue
        end = _match_end(data, pos, cand, extend_limit)
        _emit_sequence(out, data[anchor:pos], pos - cand, end - pos)
        pos = anchor = end
    _emit_literals(out, data[anchor:])
    return bytes(out)
