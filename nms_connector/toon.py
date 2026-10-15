"""TOON - Token-Oriented Object Notation - encoder (pure).

TOON is a compact text form of the JSON data model meant for *feeding* data to a language model: YAML-like
indentation for objects, one CSV-style header plus bare rows for a uniform array of objects. On the kind of
data this plugin holds (a ship and its technology: many objects with the same keys) that is where it pays -
the keys are written once instead of once per row.

Only the encoder is here, because that is all the plugin needs; a reader would have to follow the strict
decoding rules and nothing here reads TOON back.

Format reference (2026-10-15): https://github.com/wisamidris77/toon - objects ``key: value``, two spaces
per level; a primitive array ``tags[3]: a,b,c``; a uniform array of objects
``items[2]{sku,qty}:`` with one indented row of values per entry; anything else falls back to the list form
``- key: value``. Strings stay unquoted unless they would be ambiguous (empty, padded with spaces, holding
the delimiter, a colon, a quote, a backslash or a control character, or looking like a number, a boolean or
null); ``true``/``false``/``null`` and finite numbers are bare, with no exponent form.
"""

from __future__ import annotations

import math
import re

INDENT = "  "
#: What a bare (unquoted) string may not be or contain: it must not read back as something else.
LOOKS_SPECIAL = re.compile(r"^(?:true|false|null)$|^-?\d+(?:\.\d+)?$", re.I)
NEEDS_QUOTES = ('"', "\\", ":", ",", "\t", "|", "\n", "\r")


def encode(value, indent: int = 0) -> str:
    """One value as TOON. A dict at the root becomes its lines; everything else becomes a single line."""
    if isinstance(value, dict):
        return "\n".join(_object_lines(value, indent))
    return f"{INDENT * indent}{scalar(value)}"


def scalar(value) -> str:
    """A primitive as TOON writes it: bare numbers, booleans and null, strings quoted only when needed."""
    if value is None:
        return "null"
    if value is True or value is False:
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return "null"           # TOON has no NaN or infinity
        text = f"{value:.6f}".rstrip("0").rstrip(".")
        return text or "0"
    return _string(str(value))


def _string(text: str) -> str:
    if text == "" or text != text.strip() or text.startswith("- ") \
            or LOOKS_SPECIAL.match(text) or any(c in text for c in NEEDS_QUOTES) \
            or any(ord(c) < 0x20 for c in text):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
        return f'"{escaped}"'
    return text


def _is_primitive(value) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def table_fields(rows: list) -> list[str] | None:
    """The shared field names when these rows can be written as one table, else None.

    A table needs every row to be an object with the same keys and only primitive values - the case TOON
    saves the most on, and the case a ship's technology list is."""
    if not rows or not all(isinstance(row, dict) for row in rows):
        return None
    fields = list(rows[0])
    if not fields:
        return None
    for row in rows:
        if list(row) != fields or not all(_is_primitive(v) for v in row.values()):
            return None
    return fields


def _object_lines(obj: dict, indent: int) -> list[str]:
    out = []
    for key, value in obj.items():
        name = _string(str(key))
        if isinstance(value, dict):
            out.append(f"{INDENT * indent}{name}:")
            out += _object_lines(value, indent + 1)
        elif isinstance(value, (list, tuple)):
            out += _array_lines(name, list(value), indent)
        else:
            out.append(f"{INDENT * indent}{name}: {scalar(value)}")
    return out


def _array_lines(name: str, rows: list, indent: int) -> list[str]:
    pad = INDENT * indent
    if not rows:
        return [f"{pad}{name}[0]:"]
    if all(_is_primitive(r) for r in rows):
        return [f"{pad}{name}[{len(rows)}]: " + ",".join(scalar(r) for r in rows)]
    fields = table_fields(rows)
    if fields:
        head = f"{pad}{name}[{len(rows)}]{{{','.join(_string(f) for f in fields)}}}:"
        return [head] + [f"{pad}{INDENT}" + ",".join(scalar(row[f]) for f in fields) for row in rows]
    return [f"{pad}{name}[{len(rows)}]:"] + [line for row in rows for line in _list_item_lines(row, indent + 1)]


def _list_item_lines(row, indent: int) -> list[str]:
    """One entry of a non-uniform array: '- ' then the object's own lines, the first on the hyphen."""
    pad = INDENT * indent
    if not isinstance(row, dict):
        return [f"{pad}- {scalar(row)}"]
    lines = _object_lines(row, indent + 1)
    if not lines:
        return [f"{pad}-"]
    first = lines[0].lstrip()
    return [f"{pad}- {first}"] + lines[1:]
