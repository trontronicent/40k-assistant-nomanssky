"""Stacks that can be merged: the answer to "which items are in several containers / could be one stack?".

Chat of 2026-10-08 (session cdee88f2) and the German battery after it: given only the contents of every container,
the model had to find the duplicates itself and got it wrong in four ways - it ran in a 29,000-character thinking
loop, added up two different items with the same name (GEODE_LAND + GEODE_CAVE), read "zusammengeführt" as crafting
(Codex recipes) and listed items whose stacks sit in one container as if they were spread. So the plugin does the
work: it groups the rows by item id, keeps the items with more than one stack, and says how many stacks a merge
leaves (the stack limit is the row's max). Pure: no plugin state, rows come in as ``(place, [[id, amount, max]])``.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable

# A request to put stacks together, not to craft: German and English (an umlaut may be written ue / u).
MERGE_RE = re.compile(
    r"zusammen(?:ge)?(?:f[üu]e?h|leg|fass|pack|werf)|stapel|doppelt|duplikat|mehrfach|mehr als ein|"
    r"\bmerg|consolidat|duplicate|more than one|(?:single|one|same) stack|einzigen? stack|einen stack|"
    r"(?:in|across) (?:different|several|multiple|various) (?:storage|container|inventor)|verschiedenen? (?:storage|container|lager|invent)",
    re.I)
MAX_LINES = 25                    # a vague question must not dump every inventory (6,000 characters, 70 s)
RULE = ("The player asks which stacks could be merged into fewer stacks (not for crafting or recipes). Answer only "
        "from the data section 'Stacks that can be merged': one entry per item id, copy its amounts and places, never "
        "add up items with different ids even when their names are alike, and ignore Codex recipes for this question.")


def is_merge_question(question: str) -> bool:
    return bool(MERGE_RE.search(question or ""))


def _stacks_after(total: int, maximum: int) -> int:
    return -(-total // maximum) if maximum > 0 else 0


def merge_groups(places: list[tuple[str, list]], min_stacks: int = 2) -> dict[str, dict]:
    """{item id: {stacks: [(place, amount)], total, maximum}} for every item with at least `min_stacks` stacks."""
    found: dict[str, dict] = defaultdict(lambda: {"stacks": [], "total": 0, "maximum": 0})
    for place, rows in places:
        for item_id, amount, maximum in rows:
            entry = found[item_id]
            entry["stacks"].append((place, int(amount or 0)))
            entry["total"] += int(amount or 0)
            entry["maximum"] = max(entry["maximum"], int(maximum or 0))
    return {i: e for i, e in found.items() if len(e["stacks"]) >= min_stacks}


def _saving(entry: dict) -> int:
    return len(entry["stacks"]) - _stacks_after(entry["total"], entry["maximum"])


def _line(item_id: str, entry: dict, name: str, twins: list[str]) -> str:
    where = "; ".join(f"{place}: {amount:,}" for place, amount in entry["stacks"])
    if len(entry["stacks"]) == 1:        # a named item with one stack: say so instead of leaving the model to guess
        return (f"- {name} [{item_id}]: {entry['total']:,} in 1 stack, stack limit {entry['maximum']:,} - {where} "
                "(only one stack: nothing to merge)")
    after = _stacks_after(entry["total"], entry["maximum"])
    text = (f"- {name} [{item_id}]: {entry['total']:,} in {len(entry['stacks'])} stacks, stack limit "
            f"{entry['maximum']:,} -> {after} stack{'s' if after != 1 else ''} after merging - {where}")
    if _saving(entry) <= 0:
        text += " (no saving: the amounts do not fit into fewer stacks)"
    if twins:
        text += f" (not the same item as {', '.join(twins)}: same name, other id)"
    return text


def merge_lines(places: list[tuple[str, list]], name_of: Callable[[str], str], named: set[str] | None = None) -> list[str]:
    """The 'Stacks that can be merged' section for the inventories `places` (most stacks saved first, at most
    MAX_LINES). Items whose stacks would not shrink are left out - unless the question names them (`named`): then
    the line says why nothing is saved (or that there is one stack only). An empty result says so plainly."""
    named = named or set()
    groups = {i: e for i, e in merge_groups(places, 1).items()
              if i in named or (len(e["stacks"]) > 1 and _saving(e) > 0)}
    head = ["", "Stacks that can be merged (items with more than one stack in the inventories asked about; each "
                "entry is ONE item id, 'after merging' = stacks left when the amounts are put together up to the "
                "stack limit):"]
    if not groups:
        return head + ["- none: no item has several stacks that would fit together."]
    names = {i: name_of(i) for i in groups}
    by_name: dict[str, list[str]] = defaultdict(list)
    for item_id, name in names.items():
        by_name[name].append(item_id)
    ranked = sorted(groups, key=lambda i: (i not in named, -_saving(groups[i]), -groups[i]["total"]))
    lines = [_line(i, groups[i], names[i], [t for t in by_name[names[i]] if t != i]) for i in ranked[:MAX_LINES]]
    if len(ranked) > MAX_LINES:
        lines.append(f"- ... and {len(ranked) - MAX_LINES} more items; ask about one place to see them")
    return head + lines
