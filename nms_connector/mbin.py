"""Read the item tables and language tables out of the game's MBIN files (pure).

MBIN files are binary dumps of the game's data structures: a 0x10-byte header
plus a GUID, then the root structure. Lists and dynamic strings are 16-byte
headers ``<relative offset u64, count u32, 0xAAAAAA01 u32>``; the offset counts
from the header itself, and their data is appended after the structure that
owns them. Fixed strings (ids, localisation keys) are NUL-padded fields of
0x10 or 0x20 bytes.

The structures change with game updates, so nothing here hard-codes a field
offset. Each table is calibrated from its own contents:

- the item list is the root list header with the most entries;
- the record size is (lowest data target after the list - list start) / count,
  because all records come before any data they point to;
- the item id is the 0x10 field whose values are id-like and unique;
- the name keys are the 0x20 fields ending in ``_NAME`` / ``_NAME_L``;
- the icon is the dynamic string ending in ``.DDS``;
- procedural upgrades also have a template id (``T_...``, whose technology
  entry has the icon) and a subtitle key such as ``UPGRADE_SUB_2`` whose text,
  "B-Class %NAME% Upgrade", is the displayed name.

Calibration samples at most CALIBRATION_SAMPLE records, so a table costs well
under a second.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

MARK = b"\x01\xaa\xaa\xaa"
HEADER_SPAN = range(0x10, 0x70, 0x10)   # where root list headers can sit
CALIBRATION_SAMPLE = 400
ID_RE = re.compile(r"^[A-Z0-9_]{2,15}$")
NOT_ID_SUFFIXES = ("_NAME", "_NAME_L", "_DESC", "_SUB", "_L")
SUB_RE = re.compile(r"(^|_)SUB(_\d+)?$")
MARKUP_RE = re.compile(r"<[A-Z0-9_]*>|<>")
IMAGE_RE = re.compile(r"<IMG>[A-Za-z0-9_]*<>")
KEY_RE = re.compile(r"^[A-Za-z0-9_]{2,63}$")


class MbinError(ValueError):
    """The file does not have the expected table layout."""


@dataclass(frozen=True)
class ItemRecord:
    """One entry of an item table: its id and the keys and texture the calibration found for it."""
    item_id: str
    name_key: str = ""
    lower_key: str = ""
    icon: str = ""          # game texture path, e.g. TEXTURES/UI/FRONTEND/ICONS/.../X.DDS
    template: str = ""      # procedural upgrades: id of the technology that lends its icon
    subtitle_key: str = ""  # procedural upgrades: text with %NAME% is the displayed name
    category_key: str = ""  # the subtitle the game shows under the name ("Trade Commodity", "Stellar Metal")
    desc_key: str = ""      # the item's description text


def fixed_str(data: bytes, pos: int, size: int) -> str | None:
    """A NUL-terminated fixed string field, or None when the field has no terminator."""
    field = data[pos:pos + size]
    end = field.find(b"\0")
    if end < 0:
        return None
    try:
        return field[:end].decode("ascii")
    except UnicodeDecodeError:
        return None


def dyn_bytes(data: bytes, pos: int) -> bytes:
    """The bytes of a dynamic string header at pos (b'' when empty or not a header)."""
    if pos < 0 or pos + 16 > len(data) or data[pos + 12:pos + 16] != MARK:
        return b""
    offset, length = struct.unpack_from("<QI", data, pos)
    target = pos + offset
    if not length or target + length > len(data):
        return b""
    return data[target:target + length].split(b"\0", 1)[0]


def root_list(data: bytes) -> tuple[int, int]:
    """(start, count) of the root's longest list."""
    best: tuple[int, int] | None = None
    limit = len(data)   # root headers precede the data of every list: stop at the first list's data
    for pos in HEADER_SPAN:
        if pos >= limit:
            break
        if data[pos + 12:pos + 16] != MARK:
            continue
        offset, count = struct.unpack_from("<QI", data, pos)
        start = pos + offset
        if offset and start < len(data):
            limit = min(limit, start)
        if count and start < len(data) and (best is None or count > best[1]):
            best = (start, count)
    if best is None:
        raise MbinError("no list in the root structure")
    return best


def record_size(data: bytes, start: int, count: int) -> int:
    """Size of one list record: all records precede the data they point to."""
    lowest = None
    for m in re.finditer(re.escape(MARK), data):
        pos = m.start() - 12
        if pos < start:
            continue
        offset, length = struct.unpack_from("<QI", data, pos)
        target = pos + offset
        if length and start < target <= len(data) and (lowest is None or target < lowest):
            lowest = target
    end = lowest if lowest is not None else len(data)
    size = (end - start) // count
    if size < 0x10:
        raise MbinError("records are too small to be a table")
    if (end - start) % count:
        # Padding after the records: the largest 4-aligned size that fits is the record size.
        size -= size % 4
    if start + size * count > len(data):
        raise MbinError("records run past the end of the file")
    return size


def _records(data: bytes) -> tuple[int, int, int]:
    start, count = root_list(data)
    return start, count, record_size(data, start, count)


def _best_fixed(records: list[bytes], size: int, pred, exclude: tuple = (), min_share: float = 0.0) -> int | None:
    """Offset of the fixed-string field whose values most often satisfy pred (at least min_share of records)."""
    best, best_count = None, max(0, int(len(records) * min_share) - 1)
    for pos in range(0, len(records[0]) - size + 1, 4):
        if pos in exclude:
            continue
        hits = sum(1 for r in records if (v := fixed_str(r, pos, size)) and pred(v))
        if hits > best_count:
            best, best_count = pos, hits
    return best


def _best_dyn(data: bytes, starts: list[int], record: int, pred) -> int | None:
    best, best_count = None, 0
    for pos in range(0, record - 15, 4):
        hits = sum(1 for s in starts if pred(dyn_bytes(data, s + pos)))
        if hits > best_count:
            best, best_count = pos, hits
    return best


def _id_offset(records: list[bytes], exclude: tuple) -> int | None:
    best, best_count = None, 0
    for pos in range(0, len(records[0]) - 0x10 + 1, 4):
        if pos in exclude:
            continue
        values = [fixed_str(r, pos, 0x10) for r in records]
        good = [v for v in values if v and ID_RE.match(v) and not v.endswith(NOT_ID_SUFFIXES)]
        if len(good) > best_count and len(set(good)) == len(good):
            best, best_count = pos, len(good)
    return best if best_count >= max(1, len(records) // 2) else None


def parse_item_table(data: bytes) -> dict[str, ItemRecord]:
    """Every record of an item table (products, substances, technology, ...) by id."""
    start, count, size = _records(data)
    starts = [start + i * size for i in range(count)]
    sample = [data[s:s + size] for s in starts[:CALIBRATION_SAMPLE]]
    sample_starts = starts[:CALIBRATION_SAMPLE]

    name_off = _best_fixed(sample, 0x20, lambda v: v.endswith("_NAME"))
    lower_off = _best_fixed(sample, 0x20, lambda v: v.endswith("_NAME_L"))
    if lower_off is None:
        lower_off = _best_fixed(sample, 0x20, lambda v: v.endswith("_L"))
    id_off = _id_offset(sample, tuple(p for p in (name_off, lower_off) if p is not None))
    if id_off is None:
        raise MbinError("no id field")
    icon_off = _best_dyn(data, sample_starts, size, lambda b: b.upper().endswith(b".DDS"))
    # Only real columns count: a stray value (a description key starting with T_) must not become one.
    template_off = _best_fixed(sample, 0x10, lambda v: v.startswith("T_"), exclude=(id_off,), min_share=0.5)
    sub_off = _best_fixed(sample, 0x20, lambda v: bool(SUB_RE.search(v)), min_share=0.5)
    # Subtitle and description are dynamic strings holding a localisation key (UI_FUEL1_SUB, UI_FUEL_1_DESC).
    cat_off = _best_dyn(data, sample_starts, size, lambda b: b.endswith(b"_SUB"))
    desc_off = _best_dyn(data, sample_starts, size, lambda b: b.endswith((b"_DESC", b"_DESCRIPTION")))

    items: dict[str, ItemRecord] = {}
    for s in starts:
        rec = data[s:s + size]
        item_id = fixed_str(rec, id_off, 0x10)
        if not item_id or item_id in items:
            continue
        items[item_id] = ItemRecord(
            item_id=item_id,
            name_key=(fixed_str(rec, name_off, 0x20) or "") if name_off is not None else "",
            lower_key=(fixed_str(rec, lower_off, 0x20) or "") if lower_off is not None else "",
            icon=dyn_bytes(data, s + icon_off).decode("ascii", "replace") if icon_off is not None else "",
            template=(fixed_str(rec, template_off, 0x10) or "") if template_off is not None else "",
            subtitle_key=(fixed_str(rec, sub_off, 0x20) or "") if sub_off is not None else "",
            category_key=_dyn_key(data, s, cat_off),
            desc_key=_dyn_key(data, s, desc_off),
        )
    return items


def _dyn_key(data: bytes, start: int, offset: int | None) -> str:
    """A localisation key held in a dynamic string field, or '' when absent or not key-like."""
    if offset is None:
        return ""
    raw = dyn_bytes(data, start + offset)
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return ""
    return text if KEY_RE.match(text) else ""


def parse_language_table(data: bytes, wanted: set[str] | None = None) -> dict[str, str]:
    """Localisation entries {key: text} of one language file (only `wanted` keys when given).

    Each entry is the key (0x20 fixed string) followed by one dynamic string
    per language; a language file fills only its own slot.
    """
    start, count, size = _records(data)
    out: dict[str, str] = {}
    for i in range(count):
        base = start + i * size
        key = fixed_str(data, base, 0x20)
        if not key or (wanted is not None and key not in wanted):
            continue
        for slot in range(base + 0x20, base + size - 15, 0x10):
            text = dyn_bytes(data, slot)
            if text:
                out[key] = text.decode("utf-8", "replace")
                break
    return out


def clean_text(text: str | None) -> str | None:
    """Remove the game's colour markup (<TECHNOLOGY>…<>) from a text; a button image (<IMG>FE_ALT1<>, drawn
    as the key to press) becomes "[button]" instead of leaving its id in the sentence."""
    if not text:
        return None
    return MARKUP_RE.sub("", IMAGE_RE.sub("[button]", text)).strip() or None


def display_name(record: ItemRecord, strings: dict[str, str]) -> str | None:
    """The name the game shows for an item in one language, or None when unknown."""
    base = clean_text(strings.get(record.lower_key)) or clean_text(strings.get(record.name_key))
    template = strings.get(record.subtitle_key) if record.subtitle_key else None
    if template and "%NAME%" in template and base:
        return clean_text(template.replace("%NAME%", base))
    return base

