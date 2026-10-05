"""Tests for item names and icons from the game files: no game installation needed.

HGPAK archives, MBIN item tables and language tables are built synthetically in
the real on-disk formats (see nms_connector/hgpak.py and mbin.py), so the
readers and the offset calibration run exactly as on the game's files.
"""

import asyncio
import hashlib
import io
import json
import struct
from pathlib import Path

import pytest

from nms_connector import create_plugin
from nms_connector.game_install import GameInstall, find_game, language_label, nms_language, parse_vdf
from nms_connector.gamedata import GameData, icon_file_name, item_key
from nms_connector.hgpak import CHUNK_SIZE, Pak, PakError, PakSet
from nms_connector.mbin import ItemRecord, display_name, parse_item_table, parse_language_table
from test_connector import FakeCtx, make_save, obfuscated_save, write_mapping
from viewutil import section

MARK = b"\x01\xaa\xaa\xaa"

# --------------------------------------------------------------------------- builders


def build_table(records: list[dict], layout: dict[str, tuple[int, str]], size: int) -> bytes:
    """An MBIN with a root list of `records` (field -> value) laid out as `layout` (field -> (offset, kind)).

    kind 'f16' / 'f32' = fixed string field, 'dyn' = dynamic string (data appended after the records).
    """
    start = 0x30
    body = bytearray(size * len(records))
    strings = bytearray()
    strings_base = start + len(body)
    for i, rec in enumerate(records):
        for field, value in rec.items():
            offset, kind = layout[field]
            pos = i * size + offset
            if kind in ("f16", "f32"):
                width = 0x10 if kind == "f16" else 0x20
                raw = value.encode("ascii")
                body[pos:pos + width] = raw + bytes(width - len(raw))
            else:
                raw = value.encode("utf-8") + b"\0"
                target = strings_base + len(strings)
                body[pos:pos + 16] = struct.pack("<QI", target - (start + pos), len(raw)) + MARK
                strings += raw
                strings += bytes(-len(strings) % 8)
    header = b"\xcc" * 8 + struct.pack("<I", 3300) + bytes(20)
    list_header = struct.pack("<QI", start - 0x20, len(records)) + MARK
    return header + list_header + bytes(start - 0x30) + bytes(body) + bytes(strings)


def build_language(entries: dict[str, str], slot: int, slots: int = 3) -> bytes:
    """A language MBIN: per entry a 0x20 key and `slots` dynamic strings, only `slot` filled."""
    layout = {"key": (0, "f32"), "text": (0x20 + slot * 0x10, "dyn")}
    return build_table([{"key": k, "text": v} for k, v in entries.items()], layout, 0x20 + slots * 0x10)


def build_pak(files: dict[str, bytes], compressed: bool = False, raw_first_chunk: bool = False) -> bytes:
    """An HGPAK v2 archive holding `files` (zstd chunks when compressed)."""
    names = list(files)
    blobs = [b"\r\n".join(n.encode() for n in names) + b"\r\n"] + [files[n] for n in names]
    count = len(blobs)
    index_end = 0x30 + 0x20 * count
    if not compressed:
        offsets, pos = [], index_end
        for blob in blobs:
            offsets.append(pos)
            pos += len(blob)
        entries = b"".join(hashlib.md5(b"").digest() + struct.pack("<QQ", o, len(b)) for o, b in zip(offsets, blobs))
        header = b"HGPAK\0\0\0" + struct.pack("<QQQ?7xQ", 2, count, 0, False, index_end)
        return header + entries + b"".join(blobs)
    import zstandard
    stream, offsets = bytearray(), []
    for blob in blobs:
        offsets.append(len(stream))
        stream += blob
    chunks = [bytes(stream[i:i + CHUNK_SIZE]) for i in range(0, len(stream), CHUNK_SIZE)]
    stored = [c if (raw_first_chunk and i == 0 and len(c) == CHUNK_SIZE) else zstandard.ZstdCompressor().compress(c)
              for i, c in enumerate(chunks)]
    data_offset = index_end + 8 * len(stored)
    data_offset += -data_offset % 16
    entries = b"".join(hashlib.md5(b"").digest() + struct.pack("<QQ", data_offset + o, len(b))
                       for o, b in zip(offsets, blobs))
    header = b"HGPAK\0\0\0" + struct.pack("<QQQ?7xQ", 2, count, len(stored), True, data_offset)
    out = bytearray(header + entries + struct.pack(f"<{len(stored)}Q", *(len(c) for c in stored)))
    out += bytes(data_offset - len(out))
    for chunk in stored:
        out += chunk + bytes(-len(chunk) % 16)
    return bytes(out)


# Product-table-like layout with the id NOT first and a unique decoy field (the description key).
PRODUCT_LAYOUT = {"desc": (0x10, "f16"), "icon": (0x30, "dyn"), "id": (0x50, "f16"),
                  "name": (0x60, "f32"), "lower": (0x80, "f32"), "cat": (0xA0, "dyn"), "text": (0xB0, "dyn")}
PRODUCTS = [
    {"desc": "CASING_DESC", "icon": "TEXTURES/UI/FRONTEND/ICONS/U4PRODUCTS/PRODUCT.CASING.DDS", "id": "CASING",
     "name": "CASING_NAME", "lower": "CASING_NAME_L", "cat": "CRAFTPROD_SUB", "text": "CASING_DESC"},
    {"desc": "FUEL1_DESC", "icon": "TEXTURES/UI/FRONTEND/ICONS/U4SUBSTANCES/SUBSTANCE.FUEL.1.DDS", "id": "FUEL1",
     "name": "UI_FUEL_1_NAME", "lower": "UI_FUEL_1_NAME_L", "cat": "UI_FUEL1_SUB", "text": "UI_FUEL_1_DESC"},
    {"desc": "CATA_DESC", "icon": "TEXTURES/UI/FRONTEND/ICONS/U4SUBSTANCES/SUBSTANCE.CATALYST.1.DDS",
     "id": "CATALYST1", "name": "UI_CATA_NAME", "lower": "UI_CATA_NAME_L", "cat": "UI_CATA_SUB"},
    {"desc": "T_COLD_DESC", "icon": "TEXTURES/UI/FRONTEND/ICONS/TECHNOLOGY/RENDER.PROTECTCOLD.DDS",
     "id": "T_COLDPROT", "name": "TEMPLATE_NAME", "lower": "TEMPLATE_NAME_L"},
]
# Procedural-upgrade-like layout: name key ending in _L, template id, %NAME% subtitle, no icon of its own.
UPGRADE_LAYOUT = {"lower": (0x00, "f32"), "id": (0x20, "f16"), "template": (0x30, "f16"),
                  "sub": (0x40, "f32"), "pad": (0x60, "dyn")}
UPGRADES = [{"lower": "UI_COLD_NAME_CORE_L", "id": f"UP_COLD{i}", "template": "T_COLDPROT",
             "sub": f"UPGRADE_SUB_{i}", "pad": "x"} for i in (1, 2, 3)]
ENGLISH = {"CASING_NAME_L": "Metal Plating", "UI_FUEL_1_NAME_L": "Carbon", "UI_CATA_NAME_L": "<SPECIAL>Sodium<>",
           "UI_COLD_NAME_CORE_L": "Thermal Protection", "UPGRADE_SUB_1": "C-Class %NAME% Upgrade",
           "UPGRADE_SUB_2": "B-Class %NAME% Upgrade", "UPGRADE_SUB_3": "A-Class %NAME% Upgrade",
           "CRAFTPROD_SUB": "Crafted Technology Component", "UI_FUEL1_SUB": "Fuel Element",
           "UI_CATA_SUB": "Catalytic Element", "UI_FUEL_1_DESC": "A <FUEL>basic<> fuel.\n\n\n\nMined from plants."}
GERMAN = {"CASING_NAME_L": "Metallplatten", "UI_FUEL_1_NAME_L": "Kohlenstoff", "UI_CATA_NAME_L": "Natrium",
          "UI_COLD_NAME_CORE_L": "Wärmeschutz", "UPGRADE_SUB_2": "%NAME%-Upgrade der B-Klasse",
          "UI_FUEL1_SUB": "Brennstoff-Element", "UI_CATA_SUB": "Catalytic Element"}


def dds(color=(200, 30, 30, 255), size=128) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (size, size), color).save(buf, "DDS")
    return buf.getvalue()


def make_game(root: Path, english=None, german=None) -> GameInstall:
    """A fake installation: three paks named like the game's, with tables, languages and icons."""
    pcbanks = root / "GAMEDATA" / "PCBANKS"
    pcbanks.mkdir(parents=True)
    (pcbanks / "NMSARC.Precache.pak").write_bytes(build_pak({
        "metadata/reality/tables/nms_reality_gcproducttable.mbin": build_table(PRODUCTS, PRODUCT_LAYOUT, 0xC0),
        "metadata/reality/tables/nms_reality_gcproceduraltechnologytable.mbin": build_table(UPGRADES, UPGRADE_LAYOUT, 0x80),
    }))
    (pcbanks / "NMSARC.MetadataEtc.pak").write_bytes(build_pak({
        "language/nms_loc1_english.mbin": build_language(english or ENGLISH, slot=0),
        "language/nms_loc1_german.mbin": build_language(german or GERMAN, slot=2),
    }))
    (pcbanks / "NMSARC.TexUI.pak").write_bytes(build_pak({
        "textures/ui/frontend/icons/u4substances/substance.fuel.1.dds": dds(),
        "textures/ui/frontend/icons/technology/render.protectcold.dds": dds((30, 30, 200, 255)),
    }))
    return GameInstall(root, "100", "german", "steam")


# --------------------------------------------------------------------------- installation


def test_steam_library_manifest_gives_folder_build_and_language(tmp_path):
    """The game is found in a second Steam library (escaped Windows path in libraryfolders.vdf); its
    build id and Steam's language for it ('german') come from appmanifest_275850.acf."""
    steam, library = tmp_path / "Steam", tmp_path / "Lib"
    (steam / "steamapps").mkdir(parents=True)
    escaped = str(library).replace("\\", "\\\\")
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{escaped}"\n\t}}\n}}\n', encoding="utf-8")
    (library / "steamapps" / "common" / "No Man's Sky" / "GAMEDATA" / "PCBANKS").mkdir(parents=True)
    (library / "steamapps" / "appmanifest_275850.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"275850"\n\t"installdir"\t\t"No Man\'s Sky"\n\t"buildid"\t\t"25625620"\n'
        '\t"UserConfig"\n\t{\n\t\t"language"\t\t"german"\n\t}\n}\n', encoding="utf-8")
    game = find_game(env={}, roots=[steam])
    assert game is not None and game.root == library / "steamapps" / "common" / "No Man's Sky"
    assert (game.build_id, game.language, game.source) == ("25625620", "german", "steam")
    assert find_game(env={"NMS_LANGUAGE": "latam"}, roots=[steam]).language == "latinamericanspanish"
    assert find_game(env={}, roots=[tmp_path / "nothing"]) is None


def test_game_dir_override_and_language_codes(tmp_path):
    """NMS_GAME_DIR selects a folder (None when it has no PCBANKS); Steam codes map to the game's file
    suffixes, unknown ones fall back to English, and labels are the language's own name."""
    (tmp_path / "GOG" / "GAMEDATA" / "PCBANKS").mkdir(parents=True)
    game = find_game(env={"NMS_GAME_DIR": str(tmp_path / "GOG"), "NMS_LANGUAGE": "french"})
    assert game.source == "NMS_GAME_DIR" and game.build_id is None and game.language == "french"
    assert find_game(env={"NMS_GAME_DIR": str(tmp_path / "missing")}) is None
    assert [nms_language(c) for c in ("koreana", "schinese", "brazilian", "klingon", None)] == \
        ["korean", "simplifiedchinese", "brazilianportuguese", "english", "english"]
    assert language_label("german") == "Deutsch" and language_label("latinamericanspanish").startswith("Español")
    assert parse_vdf('"a" { "b" "c\\\\d" }') == {"a": {"b": "c\\d"}}


# --------------------------------------------------------------------------- archives


def test_uncompressed_pak_lists_and_reads_files(tmp_path):
    """An uncompressed HGPAK: the manifest gives lower-case names, files read back exactly, and a
    missing name is a KeyError."""
    path = tmp_path / "a.pak"
    path.write_bytes(build_pak({"Dir/One.bin": b"first", "dir/two.bin": b"second" * 100}))
    with Pak(path) as pak:
        assert set(pak.names) == {"dir/one.bin", "dir/two.bin"}
        assert pak.read("DIR/ONE.BIN") == b"first" and pak.read("dir/two.bin") == b"second" * 100
        with pytest.raises(KeyError):
            pak.read("dir/three.bin")


def test_compressed_pak_reads_across_chunks_and_stored_chunks(tmp_path):
    """zstd chunks of 64 KiB: a file spanning several chunks reads back exactly, and a chunk stored raw
    (stored size == 64 KiB) is used as is - both happen in the game's paks."""
    pytest.importorskip("zstandard")
    big = bytes(range(256)) * 700 + b"tail"          # ~175 KiB: crosses chunk boundaries
    path = tmp_path / "c.pak"
    path.write_bytes(build_pak({"a/small.txt": b"hello", "a/big.bin": big, "a/after.txt": b"end"},
                               compressed=True, raw_first_chunk=True))
    with Pak(path) as pak:
        assert pak.compressed and pak.read("a/big.bin") == big
        assert pak.read("a/small.txt") == b"hello" and pak.read("a/after.txt") == b"end"


def test_non_pak_and_other_versions_are_refused(tmp_path):
    """A file without the HGPAK magic, or with another format version, raises PakError (not garbage)."""
    (tmp_path / "x.pak").write_bytes(b"PSAR" + bytes(100))
    with pytest.raises(PakError, match="not an HGPAK"):
        Pak(tmp_path / "x.pak")
    data = bytearray(build_pak({"a": b"b"}))
    data[8:16] = struct.pack("<Q", 3)
    (tmp_path / "v3.pak").write_bytes(bytes(data))
    with pytest.raises(PakError, match="version 3"):
        Pak(tmp_path / "v3.pak")


def test_pakset_finds_files_in_any_pak(tmp_path):
    """A file outside the hinted pak is still found by searching the others."""
    (tmp_path / "A.pak").write_bytes(build_pak({"x/one": b"1"}))
    (tmp_path / "B.pak").write_bytes(build_pak({"y/two": b"2"}))
    with PakSet(tmp_path, {"y/": "A.pak"}) as paks:
        assert paks.read("y/two") == b"2" and paks.read("x/one") == b"1"
        with pytest.raises(KeyError):
            paks.read("z/none")


# --------------------------------------------------------------------------- tables and names


def test_item_table_offsets_are_calibrated_from_the_data():
    """Id, name keys and icon are found at whatever offsets the table uses - the unique description
    key before the id is not taken for the id - and the record size comes from the data layout."""
    items = parse_item_table(build_table(PRODUCTS, PRODUCT_LAYOUT, 0xC0))
    assert set(items) == {"CASING", "FUEL1", "CATALYST1", "T_COLDPROT"}
    assert items["FUEL1"] == ItemRecord("FUEL1", "UI_FUEL_1_NAME", "UI_FUEL_1_NAME_L",
                                        "TEXTURES/UI/FRONTEND/ICONS/U4SUBSTANCES/SUBSTANCE.FUEL.1.DDS",
                                        category_key="UI_FUEL1_SUB", desc_key="UI_FUEL_1_DESC")
    assert items["CATALYST1"].desc_key == "" and items["T_COLDPROT"].category_key == ""


def test_procedural_upgrade_names_come_from_the_subtitle_template():
    """Upgrades are named like the game does ('B-Class %NAME% Upgrade' with the technology's name), in
    each language's word order, markup is stripped, and an unknown key gives None."""
    items = parse_item_table(build_table(UPGRADES, UPGRADE_LAYOUT, 0x80))
    up = items["UP_COLD2"]
    assert (up.template, up.subtitle_key, up.lower_key) == ("T_COLDPROT", "UPGRADE_SUB_2", "UI_COLD_NAME_CORE_L")
    assert display_name(up, ENGLISH) == "B-Class Thermal Protection Upgrade"
    assert display_name(up, GERMAN) == "Wärmeschutz-Upgrade der B-Klasse"
    assert display_name(ItemRecord("X", lower_key="UI_CATA_NAME_L"), ENGLISH) == "Sodium"
    assert display_name(ItemRecord("X", lower_key="MISSING"), ENGLISH) is None


def test_language_table_reads_the_filled_slot_only_for_wanted_keys():
    """A language file fills one slot per entry; only the requested keys are returned (UTF-8 intact)."""
    data = build_language({"A_KEY": "Wärme", "B_KEY": "Zwei", "C_KEY": "Drei"}, slot=1)
    assert parse_language_table(data) == {"A_KEY": "Wärme", "B_KEY": "Zwei", "C_KEY": "Drei"}
    assert parse_language_table(data, {"B_KEY"}) == {"B_KEY": "Zwei"}


def test_item_keys_and_icon_names():
    """Save ids lose '^' and the procedural '#seed'; icon file names are safe lower-case .png names."""
    assert item_key("^UP_COLD1#64045") == "UP_COLD1" and item_key("^FUEL1") == "FUEL1"
    assert icon_file_name("TEXTURES/UI/FRONTEND/ICONS/U4SUBSTANCES/SUBSTANCE.FUEL.1.DDS") == "substance.fuel.1.png"
    assert icon_file_name("textures/x/odd name!.dds") == "odd-name.png"
    assert icon_file_name("TEXTURES/X.PNG") is None


# --------------------------------------------------------------------------- database


def test_translated_rarity_texts_from_memory_get_their_english(tmp_path):
    """Seen live 2026-10-04: some planet records hold flora/fauna as the game-language text ('Verloren')
    instead of a key. It is mapped back through the RARITY_* keys, so the page shows 'Lost (Verloren)'
    like every other value; a text whose RARITY_ keys mean different things in English, or that no
    RARITY_ key has, passes through unchanged (shown as read) rather than guessed."""
    english = dict(ENGLISH, RARITY_WEIRD2="Lost", RARITY_LOW9="Few", RARITY_LOW8="Uncommon",
                   RARITY_WEIRD1="Unusual", NAMEGEN_FLEET="Gone", ABUNDANCE4="Little", WEATHER_X="Rain")
    german = dict(GERMAN, RARITY_WEIRD2="Verloren", RARITY_LOW9="Wenig", RARITY_LOW8="Ungewöhnlich",
                  RARITY_WEIRD1="Ungewöhnlich", NAMEGEN_FLEET="Verloren", ABUNDANCE4="Wenig", WEATHER_X="Regen")
    game = make_game(tmp_path / "game", english, german)
    data = GameData(tmp_path / "data")
    data.load(game)
    data.resolve_texts(game, {"WEATHER_X", "Verloren", "Wenig", "Ungewöhnlich", "Nirgends"})
    assert data.text("WEATHER_X") == {"en": "Rain", "local": "Regen"}
    assert data.text("Verloren") == {"en": "Lost", "local": "Verloren"}      # not the fleet name "Gone"
    assert data.text("Wenig") == {"en": "Few", "local": "Wenig"}             # not ABUNDANCE4 "Little"
    assert data.text("Ungewöhnlich") is None and data.text("Nirgends") is None
    # The planet's other value decides between the meanings: exotic planets use the RARITY_WEIRD* texts.
    assert data.text_like("Ungewöhnlich", "RARITY_WEIRD6") == {"en": "Unusual", "local": "Ungewöhnlich"}
    assert data.text_like("Ungewöhnlich", "RARITY_MID5") == {"en": "Uncommon", "local": "Ungewöhnlich"}
    assert data.text_like("Ungewöhnlich", None) is None and data.text_like("Verloren", None)["en"] == "Lost"
    cached = GameData(tmp_path / "data")
    cached.load(game)
    assert cached.resolve_texts(game, {"Verloren"}) == 0 and cached.text("Verloren")["en"] == "Lost"
    # A cache from before (no format) gave up on the text: it is tried again, unknown keys stay unknown.
    data.texts_file.write_text(json.dumps({"build_id": "100", "language": "german", "texts": {},
                                           "unknown": ["Verloren", "NO_SUCH_KEY"]}), encoding="utf-8")
    old = GameData(tmp_path / "data")
    old.load(game)
    assert old.resolve_texts(game, {"Verloren", "NO_SUCH_KEY"}) == 1 and old.text("Verloren")["en"] == "Lost"


def test_gamedata_builds_caches_and_converts_icons(tmp_path):
    """The database is built from the paks (English + game language, upgrade icons via the template),
    cached per build, icons are converted to 64 px PNGs on demand, and a new game build rebuilds
    the cache and converts the icons again. The game folder is never written to."""
    game = make_game(tmp_path / "game")
    before = {p.name: p.read_bytes() for p in game.pcbanks.iterdir()}
    data = GameData(tmp_path / "data")
    data.load(game)
    assert data.error is None and data.language_label == "Deutsch"
    assert data.lookup("^FUEL1") == {"en": "Carbon", "local": "Kohlenstoff",
                                     "icon": "TEXTURES/UI/FRONTEND/ICONS/U4SUBSTANCES/SUBSTANCE.FUEL.1.DDS",
                                     "cat_en": "Fuel Element", "cat_local": "Brennstoff-Element",
                                     "desc_en": "A basic fuel.\n\nMined from plants."}   # markup gone, blank lines collapsed
    up = data.lookup("^UP_COLD2#12345")
    assert up["en"] == "B-Class Thermal Protection Upgrade" and up["local"] == "Wärmeschutz-Upgrade der B-Klasse"
    assert up["icon"].endswith("RENDER.PROTECTCOLD.DDS")
    assert data.lookup("^UP_COLD1")["local"] == "Wärmeschutz"   # no German subtitle text: the technology's name

    assert data.icon_name("^FUEL1") is None
    assert data.ensure_icons(game, ["^FUEL1", "^UP_COLD2#1", "^CASING", "^NOPE"]) == 2
    assert data.icon_name("^FUEL1") == "substance.fuel.1.png" and data.icon_name("^CASING") is None
    from PIL import Image
    with Image.open(data.assets_dir / "substance.fuel.1.png") as img:
        assert img.size == (64, 64) and img.format == "PNG"
    assert "PRODUCT.CASING.DDS" in (data.icon_error or "")   # the casing icon is not in the fake TexUI pak

    cached = GameData(tmp_path / "data")
    cached.load(game)
    assert cached.lookup("^FUEL1")["local"] == "Kohlenstoff" and cached.icon_name("^FUEL1")

    updated = GameData(tmp_path / "data")
    updated.load(GameInstall(game.root, "101", "german", "steam"))
    assert updated.build_id == "101" and updated.icon_name("^FUEL1") is None
    assert {p.name: p.read_bytes() for p in game.pcbanks.iterdir()} == before


def test_gamedata_reports_unreadable_game_files(tmp_path):
    """A broken pak gives a readable error and no items, instead of an exception."""
    pcbanks = tmp_path / "game" / "GAMEDATA" / "PCBANKS"
    pcbanks.mkdir(parents=True)
    (pcbanks / "NMSARC.Precache.pak").write_bytes(b"garbage")
    data = GameData(tmp_path / "data")
    data.load(GameInstall(tmp_path / "game", "1", "english", "steam"))
    assert not data.ready and "PakError" in data.error


# --------------------------------------------------------------------------- connector view


def test_view_shows_english_and_game_language_names_with_icons(tmp_path, monkeypatch):
    """With the game found, inventory tables get 'Name (English)' (with the icon) and 'Name (Deutsch)'
    columns next to the item id; items the tables do not know keep their id with empty names."""
    make_game(tmp_path / "game")
    monkeypatch.setenv("NMS_GAME_DIR", str(tmp_path / "game"))
    monkeypatch.setenv("NMS_LANGUAGE", "german")
    saves_dir = tmp_path / "NMS" / "st_1"
    saves_dir.mkdir(parents=True)
    (saves_dir / "save.hg").write_bytes(make_save(obfuscated_save()))
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "NMS"))
    data = tmp_path / "data"
    data.mkdir()
    write_mapping(data / "mapping.json")

    async def scenario():
        ctx = FakeCtx(data)
        ctx.assets_dir = data / "assets"
        plugin = create_plugin(ctx)
        await plugin._tick()
        view = plugin.view()
        result = await plugin.action("rebuild_names", {})
        await plugin.stop()
        return view, result

    view, result = asyncio.run(scenario())
    table = section(view, "Exosuit inventory")
    assert table["columns"] == ["Name (English)", "Name (Deutsch)", "Category", "Item id", "Amount", "Max"]
    rows = {r[3]: r for r in table["rows"]}
    assert rows["CATALYST1"][0] == {"text": "Sodium", "hint": "Category: Catalytic Element"}
    assert rows["CATALYST1"][1:3] == ["Natrium", "Catalytic Element"]
    fuel = rows["FUEL1"]
    assert fuel[0]["text"] == "Carbon" and fuel[0]["icon"] == "substance.fuel.1.png"
    assert fuel[0]["hint"] == "Category: Fuel Element / Brennstoff-Element\n\nA basic fuel.\n\nMined from plants."
    assert fuel[1:3] == ["Kohlenstoff", "Fuel Element / Brennstoff-Element"]
    assert (data / "assets" / "substance.fuel.1.png").is_file()
    assert result["ok"] is True and "Deutsch" in result["message"]
    source = section(view, "Source")
    assert any(i["label"] == "Item names" and "Deutsch" in i["value"] for i in source["items"])


def test_view_without_the_game_explains_where_names_come_from(tmp_path, monkeypatch):
    """No installation: one info notice says names and icons need the game files (NMS_GAME_DIR), and
    the inventory keeps a single Name column."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    monkeypatch.setattr("nms_connector.plugin.download_mapping", lambda dest: (_ for _ in ()).throw(OSError("offline")))

    async def scenario():
        plugin = create_plugin(FakeCtx(tmp_path / "data"))
        await plugin._tick()
        return plugin.view(), plugin.page.item_columns()

    view, columns = asyncio.run(scenario())
    assert any("NMS_GAME_DIR" in s.get("text", "") for s in view["sections"])
    assert columns == ["Name", "Category", "Item id", "Amount", "Max"]


def test_ids_that_are_not_items_get_the_games_icons_too(tmp_path):
    """Planet hints (UI_BONES_HINT ...) and the settlement screen's stat icons are no items, yet the game draws
    icons for them: EXTRA_ICONS names those textures, so icon lookup and conversion treat them like items."""
    from nms_connector.gamedata import EXTRA_ICONS
    gd = GameData(tmp_path / "data", tmp_path / "assets")
    assert gd.icon_texture("UI_BONES_HINT") == "TEXTURES/UI/FRONTEND/ICONS/BONES.DDS"
    assert gd.icon_texture("SETTLEMENT_NEGATIVE_HAPPINESS").endswith("SETTLEMENT/NEGATIVEHAPPINESS.DDS")
    assert gd.icon_texture("NOT_AN_ID") is None and gd.icon_name("UI_BONES_HINT") is None     # not converted yet
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "bones.png").write_bytes(b"png")
    assert gd.icon_name("UI_BONES_HINT") == "bones.png"
    assert len([k for k in EXTRA_ICONS if k.startswith("SETTLEMENT_")]) == 15


def test_button_images_in_game_texts_do_not_leave_their_id():
    """Upgrade descriptions say "Use <VAL_ON><IMG>FE_ALT1<><> to begin upgrade installation": removing only the
    tags left "Use FE_ALT1 to begin" in every tooltip (seen 2026-10-05); the image now reads "[button]"."""
    from nms_connector import mbin
    text = "Use <VAL_ON><IMG>FE_ALT1<><> to begin upgrade installation. A <TRADEABLE>moderate<> upgrade."
    assert mbin.clean_text(text) == "Use [button] to begin upgrade installation. A moderate upgrade."


def test_the_games_fill_ins_do_not_show_as_placeholders():
    """A creature egg's description has the game's per-item fill-ins (%NAME%, %READY%%EXTRA%): they come from the
    egg's seed in play, so the tooltip shows "…" instead of the placeholders (seen 2026-10-05 on 6 eggs)."""
    from nms_connector.gamedata import _plain
    assert _plain("%NAME%'s Genetic Material") == "…'s Genetic Material"
    assert _plain("A living, fertile egg, %READY%%EXTRA%  %MODIFIED%  Scans show %SIZE%.") == \
        "A living, fertile egg, … … Scans show …."
