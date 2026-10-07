"""Item names (English and the game's language) and icons from the game's own files.

Built once per game build and language from the installed game (read-only):
the item tables in ``NMSARC.Precache.pak``, the language files in
``NMSARC.MetadataEtc.pak`` and the icons in ``NMSARC.TexUI.pak``. The result is
cached in the plugin's data folder (``gamedata/items.json``); icons are
converted to 64x64 PNGs in ``assets/`` when an item first appears in a save.
The game's assets stay on this computer: nothing is uploaded or redistributed.

Blocking throughout; the plugin calls it through ``ctx.run_blocking``.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import struct
import time
from pathlib import Path

from . import logs, mbin, techstats, trade
from .game_install import GameInstall, language_label
from .hgpak import PakError, PakSet, ZstdUnavailable

CACHE_FORMAT = 7                 # 2: categories, descriptions (0.9.0); 3-4: upgrade texts, fill-ins; 5: product
                                 # base values (0.10.0); 6: substance base values too (2026-10-07)
DESC_CHARS = 600
ICON_PX = 64
TABLE_DIR = "metadata/reality/tables/"
# Tables that hold everything an inventory slot can contain; first one wins an id clash.
PROC_TABLE = "nms_reality_gcproceduraltechnologytable"
PRODUCT_TABLE = "nms_reality_gcproducttable"
SUBSTANCE_TABLE = "nms_reality_gcsubstancetable"
PRODUCT_ID_AT, PRODUCT_VALUE_AT = 0x150, 0x194  # GcProductData ID / BaseValue (libMBIN 7.04; checked by the ids, below)
# GcRealitySubstanceData ID / BaseValue. Substances (Tritium, Carbon, Cobalt ...) are the other half of what a
# player carries and have their own table; without this they showed no value at all. Calibrated against the
# game on 2026-10-07 (build 25732212) from the value the game's own tooltip shows for Tritium, 6 units each:
# 0x10C is the only plausible currency field that matches (Carbon 12, Ferrite Dust 14, Oxygen 34, Cobalt 76 -
# the game's numbers). A second field at 0x110 is also 6 for Tritium but 0 or 1 for most substances, so it is
# not a price. Checked at load like the product offsets, below.
SUBSTANCE_ID_AT, SUBSTANCE_VALUE_AT = 0xC8, 0x10C
#: Common substances the game always charges for - the anchor that tells BaseValue from the look-alike field
#: beside it (see substance_values). Ids, not names: ROCKETSUB is Tritium, FUEL1 Carbon, CAVE1 Cobalt.
ANCHOR_SUBSTANCES = ("ROCKETSUB", "FUEL1", "CAVE1", "OXYGEN")
ITEM_TABLES = ("nms_reality_gcproducttable", "nms_reality_gcsubstancetable", "nms_reality_gctechnologytable",
               "nms_reality_gcproceduraltechnologytable", "nms_basepartproducts",
               "nms_modularcustomisationproducts")
PAK_HINTS = {TABLE_DIR: "NMSARC.Precache.pak", "language/": "NMSARC.MetadataEtc.pak",
             "textures/ui/": "NMSARC.TexUI.pak"}
ICON_NAME_RE = re.compile(r"[^a-z0-9._-]+")
TEXT_KEY_RE = re.compile(r"^[A-Z0-9_]+$")       # a localisation key; anything else is already text
REVERSE_PREFIX = "RARITY_"                      # the keys translated values in planet records come from
TEXTS_FORMAT = 2                                # 2: translated values are mapped back (0.9.2)


def reverse_texts(paks: PakSet, language: str, values: set[str]) -> dict[str, list[str]]:
    """{text: [RARITY_* keys whose `language` text it is]} for texts found in memory instead of keys."""
    out: dict[str, list[str]] = {}
    for name in paks.names_matching("language/", f"_{language}.mbin"):
        for key, text in mbin.parse_language_table(paks.read(name)).items():
            text = mbin.clean_text(text)
            if key.startswith(REVERSE_PREFIX) and text in values:
                out.setdefault(text, []).append(key)
    return out


class GameDataError(RuntimeError):
    """The game's files could not be read into an item database."""


def item_key(item_id: str) -> str:
    """'^UP_COLD1#64045' -> 'UP_COLD1' (the table id; the #seed is the procedural variant)."""
    return str(item_id).lstrip("^").split("#", 1)[0]


# Icons for ids that are not in the item tables. Planet hints (GcPlanetDataResourceHint) carry an icon id next to
# their text key - read live 2026-10-04: UI_BONES_HINT/BONES, UI_SCRAP_HINT/SALVAGE, UI_BUGS_HINT/GRUBS - and these are
# the game's textures of that name (the bones icon of the frontend, the grub and buried-technology pickups of the HUD).
EXTRA_ICONS = {
    "UI_BONES_HINT": "TEXTURES/UI/FRONTEND/ICONS/BONES.DDS",
    "UI_BUGS_HINT": "TEXTURES/UI/HUD/ICONS/PICKUPS/PICKUP.GRUB.DDS",
    "UI_SCRAP_HINT": "TEXTURES/UI/HUD/ICONS/PICKUPS/PICKUP.TECHDEBRIS.DDS",
}
# The settlement screen's stat icons (textures/ui/frontend/icons/settlement/<basic|positive|negative><stat>.dds) as
# SETTLEMENT_<KIND>_<STAT>, e.g. SETTLEMENT_NEGATIVE_HAPPINESS (settlements.stat_icon_id).
EXTRA_ICONS.update({f"SETTLEMENT_{kind.upper()}_{stat.upper()}": f"TEXTURES/UI/FRONTEND/ICONS/SETTLEMENT/{kind.upper()}{stat.upper()}.DDS"
                    for kind in ("basic", "positive", "negative")
                    for stat in ("happiness", "production", "maintenance", "alert", "population")})


def _frigate_icons() -> dict[str, str]:
    from .frigates import icon_textures      # the fleet screen's class and trait icons
    return icon_textures()


EXTRA_ICONS.update(_frigate_icons())


def icon_file_name(texture: str) -> str | None:
    """'TEXTURES/UI/.../SUBSTANCE.FUEL.1.DDS' -> 'substance.fuel.1.png' (valid asset name), or None."""
    base = texture.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if not base.endswith(".dds"):
        return None
    name = ICON_NAME_RE.sub("-", base[:-4]).strip("-.") + ".png"
    return name if name[0].isalnum() and len(name) <= 120 else None


FILL_IN_RE = re.compile(r"(%[A-Z0-9_]+%)+")      # the game's per-item fill-ins: %NAME%, %SIZE%, %READY%%EXTRA%


def _plain(text: str | None) -> str | None:
    """A game text without colour markup, with collapsed blank lines and spaces, cut to DESC_CHARS. The game's
    fill-ins (a creature egg's "%NAME%'s Genetic Material", "%SIZE% and %TRAIT%") come from the item's seed in
    play; the plugin cannot know them, so each becomes "…" instead of showing the placeholder."""
    text = mbin.clean_text(text)
    if not text:
        return None
    text = FILL_IN_RE.sub("…", text)
    text = re.sub(r"\n{3,}", "\n\n", text.replace("\r", ""))
    text = re.sub(r"[ \t]{2,}", " ", text)        # where a removed fill-in or button image stood
    return text if len(text) <= DESC_CHARS else text[:DESC_CHARS - 1].rstrip() + "…"


def build_items(paks: PakSet, language: str) -> dict[str, dict]:
    """{id: {"en", "local", "icon", "cat_en", "cat_local", "desc_en", "desc_local"}} for every item in the game's
    tables (category = the subtitle the game shows under an item's name; *_local only when it differs)."""
    records: dict[str, mbin.ItemRecord] = {}
    upgrade_texts: dict[str, tuple[str, str]] = {}   # procedural upgrades: (description key, upgraded tech's name key)
    product_data = b""
    substance_data = b""
    for table in ITEM_TABLES:
        try:
            data = paks.read(f"{TABLE_DIR}{table}.mbin")
        except KeyError:
            continue  # a table renamed by a game update: the others still work
        if table == PROC_TABLE:
            upgrade_texts = techstats.procedural_texts(data)
        if table == PRODUCT_TABLE:
            product_data = data
        if table == SUBSTANCE_TABLE:
            substance_data = data
        try:
            parsed = mbin.parse_item_table(data)
        except mbin.MbinError:
            continue
        for key, record in parsed.items():
            records.setdefault(key, record)
    if not records:
        raise GameDataError("no item table could be read from the game files")

    wanted = {k for r in records.values()
              for k in (r.name_key, r.lower_key, r.subtitle_key, r.category_key, r.desc_key) if k}
    wanted |= {k for keys in upgrade_texts.values() for k in keys}
    languages = ["english"] if language == "english" else ["english", language]
    strings: dict[str, dict[str, str]] = {}
    for lang in languages:
        merged: dict[str, str] = {}
        files = paks.names_matching("language/", f"_{lang}.mbin")
        if not files:
            raise GameDataError(f"the game has no '{lang}' language files")
        for name in files:
            for key, text in mbin.parse_language_table(paks.read(name), wanted).items():
                merged.setdefault(key, text)
        strings[lang] = merged

    # keep_zero: an item the tables list with value 0 is one the game cannot sell ("value": 0 - the persona says so
    # instead of "unknown"); an item in no value table has no "value" key at all.
    values = product_values(product_data, set(records), keep_zero=True) if product_data else {}
    # Substances carry their base value in their own table, with its own offsets.
    if substance_data:
        values.update(substance_values(substance_data, set(records), keep_zero=True))
    items: dict[str, dict] = {}
    for key, record in records.items():
        icon = record.icon or (records[record.template].icon if record.template in records else "")
        entry = {"en": mbin.display_name(record, strings["english"]), "icon": icon}
        entry["local"] = mbin.display_name(record, strings[language]) if language != "english" else entry["en"]
        for field, text_key in (("cat", record.category_key), ("desc", record.desc_key)):
            en = _plain(strings["english"].get(text_key)) if text_key else None
            if en:
                entry[f"{field}_en"] = en
                local = _plain(strings[language].get(text_key)) if language != "english" else None
                if local and local != en:
                    entry[f"{field}_local"] = local
        if key in values:
            entry["value"] = values[key]
        if key in upgrade_texts and "desc_en" not in entry:
            _add_upgrade_texts(entry, records.get(record.template), upgrade_texts[key], strings, language)
        items[key] = entry
    return items


def substance_values(data: bytes, known_ids: set[str], keep_zero: bool = False) -> dict[str, int]:
    """{substance id: base value in units} from the substance table (GcRealitySubstanceData.BaseValue - what one
    unit of Tritium, Carbon or Cobalt is worth before an economy's price factor). Same guard as the products:
    the ids at the fixed offset must be the ids the calibrated parse found (>= 90 %) and the values plausible.

    Plus an anchor, because the id check alone cannot tell this field from its neighbours: a second int sits at
    0x110 that is *also* 6 for Tritium but 0 for Carbon and Oxygen, so a one-field layout shift would pass every
    other check and silently price the player's whole cargo wrong. Every one of ANCHOR_SUBSTANCES is something
    the game charges for, so a field where any of them is free is not the price field."""
    out = _table_values(data, known_ids, SUBSTANCE_ID_AT, SUBSTANCE_VALUE_AT, keep_zero)
    if any(out.get(i, 0) <= 0 for i in ANCHOR_SUBSTANCES if i in known_ids):
        return {}
    return out


def _table_values(data: bytes, known_ids: set[str], id_at: int, value_at: int,
                  keep_zero: bool = False) -> dict[str, int]:
    """{id: base value} read at fixed offsets of a table's records, or {} when the offsets do not hold up. Items
    the game gives no value (it cannot sell them) are left out, or kept as 0 with `keep_zero`."""
    try:
        start, count = mbin.root_list(data)
        size = mbin.record_size(data, start, count)
        out = {}
        for k in range(count):
            p = start + k * size
            item_id = mbin.fixed_str(data, p + id_at, 0x10)
            if item_id:
                value, = struct.unpack_from("<i", data, p + value_at)
                out[item_id] = value
    except (struct.error, mbin.MbinError, IndexError):
        return {}
    if not out or sum(1 for i in out if i in known_ids) < 0.9 * len(out):
        return {}
    if not all(0 <= v <= 100_000_000 for v in out.values()):
        return {}
    return {i: v for i, v in out.items() if v > 0 or keep_zero}


def product_values(data: bytes, known_ids: set[str], keep_zero: bool = False) -> dict[str, int]:
    """{product id: base value in units} from the product table (GcProductData.BaseValue - what a trade good, a
    product or a curiosity is worth before an economy's price factor: trade goods 1,000 / 6,000 / 15,000 / 30,000
    / 50,000 by tier, read 2026-10-05). The fixed offsets are trusted only when the ids found there are the ids the
    calibrated table parse found (>= 90 %) and the values are plausible; else {} (no values rather than wrong ones).
    The trade-good anchor (TRA_TECH1 must be worth something) catches a layout change the id check would pass."""
    out = _table_values(data, known_ids, PRODUCT_ID_AT, PRODUCT_VALUE_AT, keep_zero)
    return out if out.get("TRA_TECH1", 1) > 0 else {}


def _add_upgrade_texts(entry: dict, template: mbin.ItemRecord | None, keys: tuple[str, str],
                       strings: dict[str, dict[str, str]], language: str) -> None:
    """A procedural upgrade's description ('A moderate upgrade for the Mining Beam ...') and category - its
    template's name and the technology it upgrades ('Upgrade Module: Mining Beam') - in English and the game's
    language (*_local only when it differs)."""
    desc_key, group_key = keys
    for suffix, lang in (("en", "english"), ("local", language)):
        if suffix == "local" and language == "english":
            break
        desc = _plain(strings[lang].get(desc_key))
        kind = mbin.display_name(template, strings[lang]) if template else None
        group = mbin.clean_text(strings[lang].get(group_key))
        category = f"{kind}: {group}" if kind and group else (group or kind)
        if suffix == "local" and desc == entry.get("desc_en"):
            desc = None
        if suffix == "local" and category == entry.get("cat_en"):
            category = None
        if desc:
            entry[f"desc_{suffix}"] = desc
        if category:
            entry[f"cat_{suffix}"] = category


class GameData:
    """The item database of one installation, plus the icons converted so far."""

    def __init__(self, data_dir: Path, assets_dir: Path | None = None):
        self.cache_file = Path(data_dir) / "gamedata" / "items.json"
        # The host serves this folder at GET /plugins/<id>/assets/<name> (ctx.assets_dir, app 3.1.0+).
        self.assets_dir = Path(assets_dir) if assets_dir else Path(data_dir) / "assets"
        self.items: dict[str, dict] = {}
        self.trading: dict = dict(trade.FALLBACK)      # economy -> needs/sells/price factors (game file or fallback)
        self.trading_source = "built-in"
        # What each technology does (stat modifiers); set by the connector once per game build (GameTables).
        self.tech: techstats.TechStats = techstats.TechStats()
        self.build_id: str | None = None
        self.language = "english"
        self.stored = False                            # True: adopted from the cache without the game files
        self._names: dict[str, list[str]] = {}
        self._names_for: dict | None = None            # the items dict `_names` was built from
        self.built_at: str | None = None
        self.build_seconds: float | None = None
        self.error: str | None = None
        self.icon_error: str | None = None
        self._texts: dict[str, dict] = {}
        self._texts_for: tuple | None = None
        self._unknown_texts: set[str] = set()

    @property
    def ready(self) -> bool:
        return bool(self.items)

    @property
    def language_label(self) -> str:
        return language_label(self.language)

    def matches(self, install: GameInstall) -> bool:
        return self.ready and self.build_id == install.build_id and self.language == install.language

    def names(self) -> dict[str, list[str]]:
        """{item id: [English name, game-language name]} of every item (names the game lacks left out). Built once
        per item database; what the persona matches a question's words against."""
        if self._names_for is not self.items:
            self._names = {i: [n for n in (e.get("en"), e.get("local")) if n] for i, e in (self.items or {}).items()}
            self._names_for = self.items
        return self._names

    def release(self) -> None:
        """Drop the item database, the texts and the name index from memory (the cache on disk stays)."""
        self.items = {}
        self._texts, self._texts_for, self._unknown_texts = {}, None, set()
        self._names, self._names_for = {}, None

    def lookup(self, item_id: str) -> dict | None:
        return self.items.get(item_key(item_id))

    def load_stored(self) -> bool:
        """Adopt the cached item database whatever build it is from - for when the game's files cannot be found.
        True when there was one."""
        cached = logs.read_json(self.cache_file, "The item database cache")
        if not isinstance(cached, dict):
            return False
        if cached.get("format") != CACHE_FORMAT or not isinstance(cached.get("items"), dict) or not cached["items"]:
            return False
        self.items = cached["items"]
        if isinstance(cached.get("trading"), dict) and cached["trading"]:
            self.trading, self.trading_source = cached["trading"], cached.get("trading_source", "game files")
        self.build_id, self.language = cached.get("build_id"), cached.get("language") or "english"
        self.built_at, self.build_seconds = cached.get("built_at"), cached.get("build_seconds")
        self.error = None
        self.stored = True
        return True

    # ------------------------------------------------------------------ build / cache

    def load(self, install: GameInstall, force: bool = False) -> None:
        """Use the cache when it fits this build and language, else build it from the game files."""
        if not force and self._load_cache(install):
            if self.trading_source == "built-in":
                self._add_trading(install)       # a cache from before 0.7.0 has no trading table
            return
        started = time.perf_counter()
        try:
            with PakSet(install.pcbanks, PAK_HINTS) as paks:
                items = build_items(paks, install.language)
                try:
                    trading = trade.parse_trading_table(paks.read(trade.TABLE_FILE))
                except KeyError:
                    trading = None
        except ZstdUnavailable as exc:
            self.error = f"{exc}. It is part of the 40k Assistant from version 3.1.0 (run its setup)."
            return
        except (OSError, PakError, GameDataError, mbin.MbinError) as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            return
        self.items, self.build_id, self.language = items, install.build_id, install.language
        self.trading, self.trading_source = (trading, "game files") if trading else (dict(trade.FALLBACK), "built-in")
        self.build_seconds = round(time.perf_counter() - started, 2)
        self.built_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.error = None
        self.stored = False
        # A rebuild means a new game build, another language, a missing cache or a forced rebuild:
        # convert the icons again too (a game update can change them under the same name).
        shutil.rmtree(self.assets_dir, ignore_errors=True)
        self._write_cache()

    def _add_trading(self, install: GameInstall) -> None:
        """Read the trading table into a cached item database that lacks it (one small file, no rebuild)."""
        try:
            with PakSet(install.pcbanks, PAK_HINTS) as paks:
                trading = trade.parse_trading_table(paks.read(trade.TABLE_FILE))
        except (KeyError, OSError, PakError, ZstdUnavailable) as exc:
            self.icon_error = f"trading table: {type(exc).__name__}: {exc}"
            return
        if trading:
            self.trading, self.trading_source = trading, "game files"
            self._write_cache()

    def _load_cache(self, install: GameInstall) -> bool:
        """Adopt the cached item database when it was built for this build and language (True), else False."""
        cached = logs.read_json(self.cache_file, "The item database cache")
        if not isinstance(cached, dict):
            return False
        if (cached.get("format") != CACHE_FORMAT or cached.get("build_id") != install.build_id
                or cached.get("language") != install.language or not isinstance(cached.get("items"), dict)):
            return False
        self.items = cached["items"]
        if isinstance(cached.get("trading"), dict) and cached["trading"]:
            self.trading, self.trading_source = cached["trading"], cached.get("trading_source", "game files")
        self.build_id, self.language = install.build_id, install.language
        self.built_at, self.build_seconds = cached.get("built_at"), cached.get("build_seconds")
        self.error = None
        self.stored = False
        return True

    def _write_cache(self) -> None:
        """Keep the item database for the next start; a disk problem is a warning, the items stay in memory."""
        try:
            self._write_cache_file()
        except OSError as exc:
            logs.warn_once(f"write:{self.cache_file}", "The item database cache %s could not be written (it is "
                           "rebuilt at every start until it can): %s: %s", self.cache_file, type(exc).__name__, exc)

    def _write_cache_file(self) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"format": CACHE_FORMAT, "build_id": self.build_id, "language": self.language,
                                   "built_at": self.built_at, "build_seconds": self.build_seconds,
                                   "items": self.items, "trading": self.trading, "trading_source": self.trading_source},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.cache_file)

    # ------------------------------------------------------------------ other texts

    @property
    def texts_file(self) -> Path:
        return self.cache_file.with_name("texts.json")

    def text(self, key: str | None) -> dict | None:
        """{"en", "local"} for a localisation key resolved earlier with resolve_texts(), else None."""
        entry = self._texts.get(key) if key else None
        return entry if entry and "en" in entry else None

    def text_like(self, value: str | None, sibling: str | None) -> dict | None:
        """text(value), or - for a translated value with several meanings - the meaning from the family of a
        sibling key on the same planet: exotic planets use RARITY_WEIRD* for flora and fauna alike, others not."""
        entry = self.text(value)
        choices = (self._texts.get(value) or {}).get("choices") if value and not entry and sibling else None
        if not choices:
            return entry
        weird = "WEIRD" in sibling
        english = {en for key, en in choices.items() if ("WEIRD" in key) == weird}
        return {"en": english.pop(), "local": value} if len(english) == 1 else None

    def resolve_texts(self, install: GameInstall, keys) -> int:
        """Look up localisation keys (weather, sentinel levels, ...) in English and the game language.

        Results are cached per build and language in gamedata/texts.json; only unknown keys cost a pass
        over the language files (~0.5 s). Keys the game does not know are remembered as unknown too.
        Returns how many keys were looked up.
        """
        if self._texts_for != (install.build_id, install.language):
            self._texts, self._unknown_texts = self._load_texts(install)
            self._texts_for = (install.build_id, install.language)
        todo = {k for k in keys if k and k not in self._texts and k not in self._unknown_texts}
        if not todo:
            return 0
        languages = ["english"] if install.language == "english" else ["english", install.language]
        found: dict[str, dict[str, str]] = {lang: {} for lang in languages}
        # Values that are already text, not keys: some planet records hold flora/fauna translated ("Verloren",
        # seen 2026-10-04). They are mapped back through the game language's RARITY_* keys (reverse_texts).
        translated = {k for k in todo if not TEXT_KEY_RE.match(k)}
        reverse: dict[str, list[str]] = {}
        try:
            with PakSet(install.pcbanks, PAK_HINTS) as paks:
                if translated and install.language != "english":
                    reverse = reverse_texts(paks, install.language, translated)
                wanted = (todo - translated) | {key for keys in reverse.values() for key in keys}
                for lang in languages:
                    for name in paks.names_matching("language/", f"_{lang}.mbin"):
                        for key, value in mbin.parse_language_table(paks.read(name), wanted).items():
                            found[lang].setdefault(key, value)
        except (OSError, PakError, ZstdUnavailable, mbin.MbinError) as exc:
            self.icon_error = f"texts: {type(exc).__name__}: {exc}"
            return 0
        for value in translated:
            # Only when every matching key means the same in English: "Ungewöhnlich" is both Unusual and
            # Uncommon, and a guess would be worse than showing the text as read.
            english = {mbin.clean_text(found["english"].get(key)) for key in reverse.get(value, [])} - {None}
            if len(english) == 1:
                self._texts[value] = {"en": english.pop(), "local": value}
            elif english:      # kept for text_like, which picks the meaning by the planet's other value
                self._texts[value] = {"choices": {key: mbin.clean_text(found["english"].get(key))
                                                  for key in reverse[value] if found["english"].get(key)}}
            else:
                self._unknown_texts.add(value)
        for key in todo - translated:
            en = mbin.clean_text(found["english"].get(key))
            if en is None:
                self._unknown_texts.add(key)
                continue
            local = mbin.clean_text(found[install.language].get(key)) if install.language != "english" else en
            self._texts[key] = {"en": en, "local": local or en}
        self._write_texts(install)
        return len(todo)

    def _load_texts(self, install: GameInstall) -> tuple[dict, set]:
        """The cached resolved texts and known-unknown keys of this build and language ({}, set() otherwise)."""
        try:
            cached = json.loads(self.texts_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}, set()
        if cached.get("build_id") != install.build_id or cached.get("language") != install.language:
            return {}, set()
        unknown = set(cached.get("unknown") or [])
        if cached.get("format", 1) < TEXTS_FORMAT:   # translated values were given up on before: try them again
            unknown = {k for k in unknown if TEXT_KEY_RE.match(k)}
        return cached.get("texts") or {}, unknown

    def _write_texts(self, install: GameInstall) -> None:
        self.texts_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.texts_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"format": TEXTS_FORMAT, "build_id": install.build_id, "language": install.language,
                                   "texts": self._texts,
                                   "unknown": sorted(self._unknown_texts)}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.texts_file)

    # ------------------------------------------------------------------ icons

    def icon_texture(self, item_id: str) -> str | None:
        """The game texture of an item's icon (item tables, else EXTRA_ICONS), or None."""
        entry = self.lookup(item_id)
        return (entry or {}).get("icon") or EXTRA_ICONS.get(item_id)

    def icon_name(self, item_id: str) -> str | None:
        """Asset name of an item's icon if it has been converted, else None."""
        texture = self.icon_texture(item_id)
        name = icon_file_name(texture) if texture else None
        return name if name and (self.assets_dir / name).is_file() else None

    def ensure_icons(self, install: GameInstall, item_ids: list[str]) -> int:
        """Convert the icons of these items that are not converted yet; returns how many were added."""
        todo: dict[str, str] = {}
        for item_id in item_ids:
            texture = self.icon_texture(item_id)
            if not texture:
                continue
            name = icon_file_name(texture)
            if name and not (self.assets_dir / name).is_file():
                todo[name] = texture
        if not todo:
            return 0
        try:
            from PIL import Image
        except ImportError:
            self.icon_error = "icons need the Python package Pillow (part of the 40k Assistant)"
            return 0
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        added = 0
        try:
            with PakSet(install.pcbanks, PAK_HINTS) as paks:
                for name, texture in todo.items():
                    try:
                        dds = paks.read(texture.lower())
                        with Image.open(io.BytesIO(dds)) as img:
                            icon = img.convert("RGBA")
                            icon.thumbnail((ICON_PX, ICON_PX), Image.Resampling.LANCZOS)
                            buf = io.BytesIO()
                            icon.save(buf, "PNG", optimize=True)
                    except (KeyError, OSError, ValueError, PakError) as exc:
                        self.icon_error = f"{texture}: {type(exc).__name__}: {exc}"
                        continue
                    tmp = self.assets_dir / f".{name}.tmp"
                    tmp.write_bytes(buf.getvalue())
                    tmp.replace(self.assets_dir / name)
                    added += 1
        except (OSError, PakError, ZstdUnavailable) as exc:
            self.icon_error = f"{type(exc).__name__}: {exc}"
        return added
