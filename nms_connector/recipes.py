"""Recipes from the game's own files: refiner and Nutrient Processor recipes, and what every item is crafted from.

* **Refiner / cooking** (``nms_reality_gcrecipetable.mbin``, GcRefinerRecipe, 0x90 per record, read 2026-10-06 on
  build 25625620): id 0x00, type key 0x20, name key 0x40, **result** {id 0x60, amount 0x70, inventory type 0x74},
  **ingredients** list header 0x78 (elements of 0x18: id 0x00, amount 0x10, type 0x14), TimeToMake 0x88 (float),
  Cooking 0x8C (bool: Nutrient Processor). Checked against the game: 2 Copper -> 1 Chromatic Metal, 2 Paraffinium
  + 1 Ferrite Dust -> 1 Ammonia, 2 Sodium -> 1 Sodium Nitrate. The inventory type (0 substance, 2 product) proves the
  order amount-then-type: Crystal Sulphide, a product, is the only type-2 ingredient of a Sodium Nitrate recipe.
* **Crafting** (GcProductData ``Requirements`` in ``nms_reality_gcproducttable.mbin``, also checked in the substance
  table): a list of the same 0x18 elements. Its offset is calibrated, not hard-coded: the list header whose
  elements name known item ids in most records (Antimatter = 25 Chromatic Metal + 20 Condensed Carbon).

Values that make no sense (few id-like results, a calibration that finds nothing) leave the book empty with an
``error``; nothing is guessed. ``RecipeBook`` answers what makes an item and what it is used in; ``item_markdown``
turns that into one Codex document per item (English and the game's language), ``write_documents`` keeps the
plugin's generated files in a Codex folder up to date - only files carrying GENERATED_MARK are ever changed or
removed, so hand-written documents are never touched.

Command line (writes the documents into the app's Codex folder):
``python tools/codex_recipes.py "J:\\40k-assistant\\knowledge_base\\No Man's Sky"`` (run again after a game update)
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import game_terms, mbin

RECIPE_FILE = "metadata/reality/tables/nms_reality_gcrecipetable.mbin"
REQUIREMENT_TABLES = ("nms_reality_gcproducttable", "nms_reality_gcsubstancetable")
RECORD = 0x90
RESULT_AT, INGREDIENTS_AT, TIME_AT, COOKING_AT = 0x60, 0x78, 0x88, 0x8C
ELEMENT = 0x18                      # {id 0x10, amount i32, inventory type i32}
MIN_VALID_SHARE = 0.9               # share of records whose result looks like an item id
MAX_AMOUNT = 100_000

GENERATED_MARK = "generated: nomanssky-plugin recipes"
ITEMS_DIR = "Items"
CATEGORY_DIRS = {"substance": "Raw materials", "product": "Products", "food": "Food"}
MAX_USES = 40                       # "used in" lines per kind before "... and N more"
TITLE_SAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass(frozen=True)
class Recipe:
    """One refiner or Nutrient Processor recipe: ingredients ((id, amount), ...) -> result (id, amount)."""
    id: str
    result: str
    amount: int
    ingredients: tuple[tuple[str, int], ...]
    cooking: bool


def _element(data: bytes, pos: int) -> tuple[str, int, int] | None:
    """(id, amount, inventory type) of one 0x18 element, None when it is not one."""
    if pos < 0 or pos + ELEMENT > len(data):
        return None
    item = mbin.fixed_str(data, pos, 0x10)
    amount, kind = struct.unpack_from("<ii", data, pos + 0x10)
    if not item or not mbin.ID_RE.match(item) or not 0 < amount <= MAX_AMOUNT or kind not in (0, 1, 2):
        return None
    return item, amount, kind


def _elements(data: bytes, header: int) -> list[tuple[str, int, int]] | None:
    """The elements of the list whose 16-byte header is at `header`; None when one of them is not an element."""
    if data[header + 12:header + 16] != mbin.MARK:
        return None
    offset, count = struct.unpack_from("<QI", data, header)
    out = []
    for j in range(count):
        element = _element(data, header + offset + j * ELEMENT)
        if element is None:
            return None
        out.append(element)
    return out


def parse_recipes(data: bytes) -> list[Recipe]:
    """Every recipe of the recipe table; raises mbin.MbinError when the layout does not fit."""
    start, count, size = mbin._records(data)
    if size != RECORD:
        raise mbin.MbinError(f"recipe records are {size:#x} bytes, expected {RECORD:#x}")
    out = []
    for k in range(count):
        base = start + k * size
        result = _element(data, base + RESULT_AT)
        ingredients = _elements(data, base + INGREDIENTS_AT)
        if result is None or not ingredients:
            continue
        out.append(Recipe(mbin.fixed_str(data, base, 0x20) or f"recipe {k}", result[0], result[1],
                          tuple((i, a) for i, a, _ in ingredients), bool(data[base + COOKING_AT])))
    if count and len(out) < MIN_VALID_SHARE * count:
        raise mbin.MbinError(f"only {len(out)} of {count} recipes look valid")
    return out


def parse_requirements(data: bytes, known_ids: set[str]) -> dict[str, list[tuple[str, int]]]:
    """{item id: [(ingredient id, amount), ...]} of a product/substance table: the item id is the record's
    id-like field among known_ids, the requirements the list header whose elements name known ids."""
    start, count, size = mbin._records(data)
    sample = range(0, count, max(1, count // 300))
    id_votes: dict[int, int] = {}
    list_votes: dict[int, int] = {}
    for k in sample:
        base = start + k * size
        for o in range(0, size - 0x10 + 1, 4):
            if mbin.fixed_str(data, base + o, 0x10) in known_ids:
                id_votes[o] = id_votes.get(o, 0) + 1
            if data[base + o + 12:base + o + 16] == mbin.MARK:
                elements = _elements(data, base + o)
                if elements and all(i in known_ids for i, _, _ in elements):
                    list_votes[o] = list_votes.get(o, 0) + 1
    if not id_votes or not list_votes:
        raise mbin.MbinError("no item id or requirement list found")
    id_at = max(id_votes, key=id_votes.get)
    req_at = max(list_votes, key=list_votes.get)
    out: dict[str, list[tuple[str, int]]] = {}
    for k in range(count):
        base = start + k * size
        item = mbin.fixed_str(data, base + id_at, 0x10)
        elements = _elements(data, base + req_at)
        if item and elements:
            out[item] = [(i, a) for i, a, _ in elements]
    return out


@dataclass
class RecipeBook:
    """All recipes of one game build; empty with `error` when the files could not be read."""
    recipes: list[Recipe] = field(default_factory=list)
    crafting: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    substances: set[str] = field(default_factory=set)     # ids of the substance table (raw materials)
    error: str | None = None

    def made_by(self, item: str, cooking: bool = False) -> list[Recipe]:
        """Refiner (or, with cooking, Nutrient Processor) recipes that make `item`, best yield per input first."""
        found = [r for r in self.recipes if r.result == item and r.cooking == cooking]
        return sorted(found, key=lambda r: (len(r.ingredients), -r.amount / max(1, sum(a for _, a in r.ingredients))))

    def used_in(self, item: str) -> dict[str, list]:
        """Where `item` is an ingredient: {"refiner": [Recipe], "cooking": [Recipe], "crafting": [product id]}."""
        uses = {"refiner": [], "cooking": [], "crafting": []}
        for r in self.recipes:
            if any(i == item for i, _ in r.ingredients):
                uses["cooking" if r.cooking else "refiner"].append(r)
        uses["crafting"] = sorted(p for p, req in self.crafting.items() if any(i == item for i, _ in req))
        return uses

    def items(self) -> set[str]:
        """Every item a recipe makes, uses or that has a crafting recipe."""
        out = set(self.crafting)
        for req in self.crafting.values():
            out |= {i for i, _ in req}
        for r in self.recipes:
            out.add(r.result)
            out |= {i for i, _ in r.ingredients}
        return out


def load(install) -> RecipeBook:
    """The recipe book of an installation (blocking: reads the game's paks); errors end up in `error`."""
    from . import hgpak
    from .gamedata import PAK_HINTS, TABLE_DIR
    if install is None:
        return RecipeBook(error="game installation not found")
    try:
        with hgpak.PakSet(install.pcbanks, PAK_HINTS) as paks:
            recipes = parse_recipes(paks.read(RECIPE_FILE))
            tables = {t: paks.read(f"{TABLE_DIR}{t}.mbin") for t in REQUIREMENT_TABLES}
        known = set()
        for data in tables.values():
            known |= set(mbin.parse_item_table(data))
        substances = set(mbin.parse_item_table(tables["nms_reality_gcsubstancetable"]))
        crafting: dict[str, list[tuple[str, int]]] = {}
        for name, data in tables.items():
            try:
                crafting.update(parse_requirements(data, known))
            except mbin.MbinError:
                if name == REQUIREMENT_TABLES[0]:       # substances may have no requirements at all
                    raise
        return RecipeBook(recipes, crafting, substances)
    except (OSError, KeyError, ValueError, hgpak.PakError, hgpak.ZstdUnavailable) as exc:
        return RecipeBook(error=f"{type(exc).__name__}: {exc}")


# ---- Codex documents ---------------------------------------------------------------------------------------
# One document per item and language (app 3.12.0 keeps the `language` front matter and prefers documents in the
# question's language): English, and the game's language when it is not English - every name, description and
# term as the game writes it in that language (game_terms), split instead of mixed (asked for 2026-10-06).

ENGLISH = "english"


def _names(lookup, item: str) -> tuple[str, str | None]:
    """(English name, game-language name or None) - the id when the game has no name for it."""
    entry = lookup(item) or {}
    en = entry.get("en") or item
    local = entry.get("local")
    return en, (local if local and local != en else None)


def name_in(lookup, item: str, language: str) -> str:
    """The item's name in `language` (the game's language falls back to English where it has no name)."""
    entry = lookup(item) or {}
    if language != ENGLISH and entry.get("local"):
        return entry["local"]
    return entry.get("en") or item


def item_label(lookup, item: str) -> str:
    """'Ammonia (Ammoniak)' - both names, for the persona's chat data."""
    en, local = _names(lookup, item)
    return f"{en} ({local})" if local else en


def _station(r: Recipe, language: str, terms) -> str:
    """Where a recipe is made, in the game's words: the smallest refiner with enough input slots, or the
    Nutrient Processor ('Tragbare Raffinerie oder größer', 'Große Raffinerie', 'Nährstoffprozessor')."""
    terms = terms or game_terms.GameTerms()
    if r.cooking:
        return terms.get("processor", language)
    larger = " or larger" if language == ENGLISH else (" oder größer" if language == "german" else " +")
    return {1: terms.get("refiner_portable", language) + larger,
            2: terms.get("refiner_medium", language) + larger}.get(len(r.ingredients), terms.get("refiner_large", language))


def recipe_line(lookup, r: Recipe, terms=None) -> str:
    """'2 Paraffinium + 1 Ferrite Dust (Ferritstaub) → 1 Ammonia (Ammoniak) · Medium Refiner or larger (Mittlere
    Raffinerie oder größer)' - both languages, for the persona."""
    terms = terms or game_terms.GameTerms()
    parts = " + ".join(f"{a} {item_label(lookup, i)}" for i, a in r.ingredients)
    station = _station(r, ENGLISH, terms)
    local_station = _station(r, terms.language, terms) if terms.language != ENGLISH else None
    if local_station is None and terms.language == ENGLISH:
        local_station = _station(r, "german", terms)        # the measured German fallback, for German questions
    return f"{parts} → {r.amount} {item_label(lookup, r.result)} · {station}" + (
        f" ({local_station})" if local_station and local_station != station else "")


def _line_in(lookup, r: Recipe, language: str, terms) -> str:
    """A recipe in one language only: '2 Paraffinium + 1 Ferritstaub → 1 Ammoniak · Mittlere Raffinerie oder größer'."""
    parts = " + ".join(f"{a} {name_in(lookup, i, language)}" for i, a in r.ingredients)
    return f"{parts} → {r.amount} {name_in(lookup, r.result, language)} · {_station(r, language, terms)}"


def kind_of(book: RecipeBook, lookup, item: str) -> str:
    """'substance', 'food' or 'product' - the Codex subfolder an item's document goes to."""
    if item in book.substances:
        return "substance"
    if any(r.result == item and r.cooking for r in book.recipes) or item.startswith("FOOD_"):
        return "food"
    return "product"


def _front(title: str, tags: list[str], language: str, mark: str) -> list[str]:
    """YAML front matter; JSON strings are valid YAML, so titles with ':' or ',' stay one value."""
    return ["---", f"title: {json.dumps(title, ensure_ascii=False)}",
            "tags: [" + ", ".join(json.dumps(t, ensure_ascii=False) for t in tags) + "]",
            f"language: {game_terms.LANGUAGE_CODES.get(language, 'en')}",
            f"# {mark} - edits are overwritten when the documents are generated again", "---", ""]


def item_markdown(book: RecipeBook, lookup, item: str, language: str = ENGLISH, terms=None) -> str:
    """One item's Codex document in one language: where it comes from (the game's description), every recipe
    that makes it, its crafting recipe and what it is used for - names and terms as the game writes them there."""
    terms = terms or game_terms.GameTerms()
    entry = lookup(item) or {}
    local_lang = language != ENGLISH
    name = name_in(lookup, item, language)
    other_lang = terms.language if not local_lang else ENGLISH
    other = name_in(lookup, item, other_lang) if other_lang != language else None
    h = lambda key, **v: game_terms.heading(key, language, **v)            # noqa: E731
    out = _front(name, [item] + ([other] if other and other != name else []) + ["recipe"], language, GENERATED_MARK)
    out += [f"# {name}", ""]
    desc = entry.get("desc_local" if local_lang else "desc_en") or entry.get("desc_en")
    if desc:
        out += [f"## {h('where_from') if kind_of(book, lookup, item) == 'substance' else h('about')}", "",
                " ".join(desc.split()), ""]
    if other and other != name:
        out += [h("other_name", lang_name=game_terms.language_name(other_lang, language), name=other), ""]
    refined = book.made_by(item)
    if refined:
        out += [f"## {h('refined')}: {name}", ""] + [f"- {_line_in(lookup, r, language, terms)}" for r in refined] + [""]
    cooked = book.made_by(item, cooking=True)
    if cooked:
        out += [f"## {h('cooked')}: {name}", ""] + [f"- {_line_in(lookup, r, language, terms)}" for r in cooked] + [""]
    crafted = book.crafting.get(item)
    if crafted:
        out += [f"## {terms.get('crafting', language)}: {name}", "",
                "- " + " + ".join(f"{a} {name_in(lookup, i, language)}" for i, a in crafted) + f" → 1 {name}", ""]
    if not (refined or cooked or crafted) and kind_of(book, lookup, item) == "substance":
        out += [f"## {terms.get('recipes', language)}", "", h("gathered", name=name), ""]
    uses = book.used_in(item)
    if any(uses.values()):
        out += [f"## {terms.get('used_for', language).rstrip(':')}", ""]
        for kind, key in (("refiner", "uses_refiner"), ("crafting", "uses_crafting"), ("cooking", "uses_cooking")):
            entries = uses[kind]
            if not entries:
                continue
            lines = ([_line_in(lookup, r, language, terms) for r in entries] if kind != "crafting" else
                     [name_in(lookup, p, language) + ": " + " + ".join(f"{a} {name_in(lookup, i, language)}"
                                                                     for i, a in book.crafting[p]) for p in entries])
            out.append(f"{h(key)} ({len(lines)}):")
            out += [f"- {line}" for line in lines[:MAX_USES]]
            if len(lines) > MAX_USES:
                out.append(f"- {h('and_more', n=len(lines) - MAX_USES)}")
            out.append("")
    # Id and category last: a search snippet comes from the first passage, which should say where it comes from.
    category = entry.get("cat_local" if local_lang else "cat_en") or entry.get("cat_en")
    out += [f"## {h('game_data')}", "", f"{h('item_id')} `{item}`" + (f" · {category}" if category else ""), ""]
    return _loose_lists("\n".join(out)).rstrip() + "\n"


def _label(language: str) -> str:
    from .game_install import language_label
    return language_label(language)


def _loose_lists(text: str) -> str:
    """A blank line between list entries: the Codex chunker splits at blank lines and hard-cuts a longer
    paragraph at 1000 characters, which cut long recipe lists mid-word (seen 2026-10-06: 'Tr  itium')."""
    return re.sub(r"\n(?=- )", "\n\n", text).replace("\n\n\n", "\n\n")


def file_name(title: str) -> str:
    """A safe Markdown file name for a title ('Ammonia (Ammoniak)' -> 'Ammonia (Ammoniak).md')."""
    name = TITLE_SAFE_RE.sub("", title).strip(" .") or "item"
    return name[:120] + ".md"


def languages_of(terms) -> list[str]:
    """English, plus the game's language when it is another one."""
    lang = getattr(terms, "language", ENGLISH) or ENGLISH
    return [ENGLISH] + ([lang] if lang not in (ENGLISH, "usenglish") else [])


def documents(book: RecipeBook, lookup, terms=None) -> dict[str, str]:
    """{relative path: Markdown} for every named item in a recipe, per language:
    '<English|Deutsch|...>/<Raw Materials|Products|Food in the game's words>/<name>.md'. Items the game gives no
    English name are skipped (unused ids)."""
    terms = terms or game_terms.GameTerms()
    folders = {"substance": "raw", "product": "products", "food": "food"}
    out: dict[str, str] = {}
    for language in languages_of(terms):
        root = _label(language)
        for item in sorted(book.items()):
            entry = lookup(item) or {}
            if not entry.get("en"):
                continue
            path = f"{root}/{terms.get(folders[kind_of(book, lookup, item)], language)}/" \
                   f"{file_name(name_in(lookup, item, language))}"
            if path in out:                              # two ids with one name: keep both, the id tells them apart
                path = path[:-3] + f" [{item}].md"
            out[path] = item_markdown(book, lookup, item, language, terms)
    return out


def write_documents(folder: Path, docs: dict[str, str], mark: str = GENERATED_MARK,
                    subdirs: tuple[str, ...] | str = ITEMS_DIR) -> dict[str, int]:
    """Write `docs` below `folder` (the library's folder in the Codex folder): new and changed files are written,
    unchanged ones left alone (the Codex sync then skips them), generated files under `subdirs` no longer produced
    are removed (and folders left empty). Only files containing `mark` (the generator's own) are ever changed or
    removed. Returns the counts."""
    folder = Path(folder)
    counts = {"written": 0, "unchanged": 0, "removed": 0, "kept_handwritten": 0}
    for rel, text in docs.items():
        path = folder / rel
        if path.exists():
            old = path.read_text(encoding="utf-8")
            if old == text:
                counts["unchanged"] += 1
                continue
            if mark not in old:
                counts["kept_handwritten"] += 1
                continue
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        tmp.replace(path)
        counts["written"] += 1
    wanted = {(folder / rel).resolve() for rel in docs}
    for subdir in ([subdirs] if isinstance(subdirs, str) else subdirs):
        root = folder / subdir
        if not root.exists():
            continue
        for path in root.rglob("*.md"):
            if path.resolve() not in wanted and mark in path.read_text(encoding="utf-8", errors="replace"):
                path.unlink()
                counts["removed"] += 1
        for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)) + [root]:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
    return counts


# Folders of the mixed-language documents written before 2026-10-06 (removed when the split ones are written).
LEGACY_DIRS = ("Items", "Worlds")


CODEX_LIBRARY = "No Man's Sky"      # the library the persona's setup suggests (companion.PERSONA_SETUP)


def codex_library_folder(plugin_root: Path, environ=None) -> Path:
    """The No Man's Sky library in the app's Codex folder, found as the app finds it: $CODEX_FOLDER, else
    knowledge_base/ in the app folder (the installed plugin sits in <app>/plugins/<id>)."""
    import os
    env = os.environ if environ is None else environ
    override = str(env.get("CODEX_FOLDER") or "").strip()
    root = Path(override) if override else Path(plugin_root).resolve().parents[1] / "knowledge_base"
    return root / CODEX_LIBRARY


def default_items_path(here: Path | None = None) -> Path:
    """The plugin's item cache: next to an installed plugin (plugins/nomanssky -> plugins/.data/nomanssky), else in
    the app beside a development checkout (stc-repos/<plugin> -> 40k-assistant/plugins/.data/nomanssky); the first
    that exists, else the installed location (the error then names it)."""
    here = (here or Path(__file__)).resolve()
    installed = here.parents[2] / ".data" / "nomanssky" / "gamedata" / "items.json"
    checkout = here.parents[3] / "40k-assistant" / "plugins" / ".data" / "nomanssky" / "gamedata" / "items.json"
    return next((p for p in (installed, checkout) if p.is_file()), installed)


def main(argv: list[str] | None = None) -> int:
    """Generate the item and world-type documents, per language, into a Codex library folder (argument), from the
    installed game and the plugin's item cache (names and descriptions)."""
    import argparse
    from .game_install import find_game
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("folder", help="the No Man's Sky library folder in the Codex folder")
    parser.add_argument("--items", default=str(default_items_path()),
                        help="the plugin's item cache (gamedata/items.json in its data folder)")
    args = parser.parse_args(argv)
    install = find_game()
    book = load(install)
    if book.error:
        print(f"Recipes unavailable: {book.error}")
        return 1
    from . import worlds
    terms = game_terms.load(install)
    world_book = worlds.load(install)
    if world_book.error:
        print(f"World types unavailable: {world_book.error}")
        return 1
    items = json.loads(Path(args.items).read_text(encoding="utf-8")).get("items") or {}
    roots = tuple(_label(lang) for lang in languages_of(terms))
    docs = documents(book, items.get, terms)
    print(f"{len(book.recipes)} recipes, {len(book.crafting)} crafting recipes -> {len(docs)} item documents "
          f"in {', '.join(roots)}")
    print("items:", write_documents(Path(args.folder), docs, GENERATED_MARK, roots + LEGACY_DIRS))
    world_docs = world_book.documents(items.get, terms)
    print(f"{len(world_docs)} world-type documents ->",
          write_documents(Path(args.folder), world_docs, worlds.GENERATED_MARK, roots + LEGACY_DIRS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
