"""LZ4 block decompression (pure Python, no dependency).

No Man's Sky compresses its save files in LZ4 *blocks* (not the LZ4 frame
format). A 3 MB save decodes in well under a second, which is plenty for a file
the game writes every few minutes.
"""


class LZ4Error(ValueError):
    """The input is not a valid LZ4 block."""


def decompress_block(src: bytes, out_size: int) -> bytes:
    """Decompress one LZ4 block whose uncompressed size is known."""
    dst = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        literals = token >> 4
        if literals == 15:
            while True:
                if i >= n:
                    raise LZ4Error("truncated literal length")
                extra = src[i]
                i += 1
                literals += extra
                if extra != 255:
                    break
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
        if offset == 0 or offset > len(dst):
            raise LZ4Error("invalid match offset")
        length = token & 15
        if length == 15:
            while True:
                if i >= n:
                    raise LZ4Error("truncated match length")
                extra = src[i]
                i += 1
                length += extra
                if extra != 255:
                    break
        length += 4
        start = len(dst) - offset
        if length <= offset:
            dst += dst[start:start + length]
        else:  # overlapping copy repeats the last `offset` bytes
            for k in range(length):
                dst.append(dst[start + k])
    if len(dst) != out_size:
        raise LZ4Error(f"decoded {len(dst)} bytes, expected {out_size}")
    return bytes(dst)
