"""RAM use of the plugin: pak sessions (each file index built once, freed at the end), correct pak hints, filtered
language parsing, the compact star seed table, and releasing everything on stop."""

import asyncio
import logging
from pathlib import Path

import pytest

from nms_connector import frigates, hgpak, logs, mbin, settlements, starmap
from nms_connector.hgpak import Pak, PakError, PakSet
from test_connector import FakeCtx, create_plugin
from test_gamedata import build_pak


@pytest.fixture(autouse=True)
def fresh_log_memory():
    """A clean 'already logged' memory for the stale-hint warnings."""
    logs.reset()
    yield
    logs.reset()


@pytest.fixture
def opens(monkeypatch):
    """The list of paks opened (a Pak is created = its file index is built) during a test."""
    opened = []
    real = Pak.__init__

    def counting(self, path):
        opened.append(Path(path).name)
        real(self, path)
    monkeypatch.setattr(Pak, "__init__", counting)
    return opened


def _banks(tmp_path, **paks):
    folder = tmp_path / "PCBANKS"
    folder.mkdir()
    for name, files in paks.items():
        (folder / f"{name}.pak").write_bytes(build_pak(files))
    return folder


def test_a_session_opens_each_pak_once_and_frees_it_at_the_end(tmp_path, opens):
    """Several PakSets (one per table loader) inside hgpak.session() share one open Pak per file; at the end the paks
    are closed and their file index dropped. Without the session every loader opened (and indexed) the pak again -
    up to 29 MB and 0.4 s each for the game's MetadataEtc."""
    banks = _banks(tmp_path, A={"x/one.mbin": b"1"}, B={"x/two.mbin": b"2"})
    with hgpak.session():
        with PakSet(banks, {"x/": "A.pak"}) as first:
            assert first.read("x/one.mbin") == b"1"
        with PakSet(banks, {"x/": "A.pak"}) as second:
            assert second.read("x/one.mbin") == b"1"
        shared = hgpak._SESSION.paks["%s" % (banks / "A.pak")]
        assert opens == ["A.pak"] and shared.names
    assert not hgpak.session_active() and shared.names == {} and shared._f.closed
    with PakSet(banks, {"x/": "A.pak"}) as outside:        # no session: each set opens its own, as before
        outside.read("x/one.mbin")
        outside.read("x/two.mbin")
    assert opens == ["A.pak", "A.pak", "B.pak"] and not outside._open


def test_sessions_nest_and_only_the_outermost_frees(tmp_path):
    """A session started inside another (the work loop's pass around a table load) keeps the paks open until the outer
    one ends, and a failing block still frees them."""
    banks = _banks(tmp_path, A={"x/one.mbin": b"1"})
    with pytest.raises(RuntimeError):
        with hgpak.session():
            with hgpak.session():
                PakSet(banks).read("x/one.mbin")
            assert hgpak.session_active()
            raise RuntimeError("boom")
    assert not hgpak.session_active() and hgpak._SESSION.depth == 0


def test_a_stale_pak_hint_is_found_by_scanning_and_logged_once(tmp_path, monkeypatch, caplog):
    """When the hinted pak lacks the file the other paks are tried (small ones first) and the file is still found,
    with one warning that the hint is stale - the 2026-10-08 finding: the frigate, settlement and globals hints were
    wrong and every load opened 7-21 paks."""
    banks = _banks(tmp_path, A={"x/other.mbin": b"o"}, B={"x/two.mbin": b"2"})
    monkeypatch.setattr(hgpak, "SCAN_WARN_OPENS", 2)
    with caplog.at_level(logging.WARNING, logger="vox-core.plugin.nomanssky"):
        with PakSet(banks, {"x/": "A.pak"}) as paks:
            assert paks.read("x/two.mbin") == b"2"
            assert paks.read("x/two.mbin") == b"2"
    assert caplog.text.count("its pak hint is stale") == 1 and "B.pak" in caplog.text
    with pytest.raises(KeyError):
        PakSet(banks).read("x/missing.mbin")


def test_the_loaders_hint_the_paks_that_really_hold_their_files():
    """The game's tables live in Precache (metadata/reality/tables) and the globals in globals.pak - checked
    2026-10-08 by scanning every pak. A hint pointing elsewhere makes every load scan up to 21 paks."""
    assert frigates.TRAIT_PAK == settlements.PERKS_PAK == hgpak.TABLE_PAK == "NMSARC.Precache.pak"
    assert settlements.GLOBALS_PAK == hgpak.GLOBALS_PAK == "NMSARC.globals.pak"


def test_the_pak_index_is_unpacked_on_demand_and_checks_bounds(tmp_path):
    """The raw index stays as bytes (no tuple per file); entries still read back exactly, and an entry number outside
    the index is a PakError instead of a struct error."""
    banks = _banks(tmp_path, A={"x/one.mbin": b"one", "x/two.mbin": b"twotwo"})
    with Pak(banks / "A.pak") as pak:
        assert pak.read("x/one.mbin") == b"one" and pak.read("X/TWO.mbin") == b"twotwo"
        assert isinstance(pak._index, bytes) and not hasattr(pak, "_entries")
        with pytest.raises(PakError):
            pak._read_entry(99)


def test_game_tables_load_inside_one_pak_session(monkeypatch):
    """GameTables.load wraps all table readers in a single session, so the pak indexes are built once per pass."""
    from nms_connector.tables import GameTables
    seen = []
    monkeypatch.setattr(GameTables, "_load_tables", lambda self, install: seen.append(hgpak.session_active()) or [])
    GameTables().load(object())
    assert seen == [True] and not hgpak.session_active()


def test_language_parsing_decodes_only_the_wanted_keys(monkeypatch):
    """parse_language_table takes a predicate as well as a set and never decodes the texts of other keys - the
    language files hold ~50,000 entries of which the books want a few hundred."""
    import struct
    size = 0x20 + 0x10 * 2
    keys = ["WANTED_A", "OTHER_B", "WANTED_C"]
    data = bytearray(0x20 + size * len(keys))
    struct.pack_into("<QI4s", data, 0x10, 0x10, len(keys), mbin.MARK)
    # Entries without a dynamic string decode to nothing; count how often a text is decoded at all.
    decoded = []
    real = mbin.dyn_bytes
    monkeypatch.setattr(mbin, "dyn_bytes", lambda d, p: decoded.append(p) or b"text")
    for k, key in enumerate(keys):
        data[0x20 + k * size:0x20 + k * size + len(key)] = key.encode()
    by_set = mbin.parse_language_table(bytes(data), {"WANTED_A", "WANTED_C"})
    by_function = mbin.parse_language_table(bytes(data), lambda key: key.startswith("WANTED"))
    assert by_set == by_function == {"WANTED_A": "text", "WANTED_C": "text"}
    assert len(decoded) == 4 and real is not None        # two per call, "OTHER_B" never decoded


def test_the_seed_table_is_three_arrays_and_matches_the_dict_form():
    """seed_table returns numpy arrays (24 bytes per system instead of ~400 for tuples and lists of Python ints) that
    find_records reads exactly like the dict form older code builds."""
    from test_starmap import ULEBSK, DELTA_SOL, YIBRAZH
    table = starmap.seed_table([ULEBSK, DELTA_SOL, YIBRAZH])
    assert len(table) == 3 and table.first.nbytes + table.keys.nbytes + table.second.nbytes == 3 * 24
    as_dict = {s: (int(k), [s] + ([int(sec)] if sec else [])) for s, k, sec in zip(table.first.tolist(), table.keys.tolist(), table.second.tolist())}
    again = starmap._as_table(as_dict)
    assert again.first.tolist() == table.first.tolist() and again.keys.tolist() == table.keys.tolist()
    assert starmap._as_table({}).first.tolist() == [] and not len(starmap._as_table(None))


def test_the_prediction_cache_is_bounded(monkeypatch):
    """starmap.predicted caches per system; it is cleared when it reaches MAX_PREDICTIONS so a long session across many
    systems cannot grow it without limit."""
    from test_starmap import ULEBSK
    monkeypatch.setattr(starmap, "MAX_PREDICTIONS", 2)
    starmap._predictions.clear()
    keys = [ULEBSK, ULEBSK + (1 << 40), ULEBSK + (2 << 40)]
    for key in keys:
        starmap.predicted(key)
    assert len(starmap._predictions) <= 2
    starmap._predictions.clear()


def test_stopping_the_plugin_releases_what_it_holds_in_ram(tmp_path, monkeypatch):
    """After stop() the item database, texts, tables, the save-derived lists, recorded planets and module caches are
    gone (a stopped or updated plugin must not leave tens of MB alive); calling it again is harmless and the plugin can
    be started again - everything is re-read from disk."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    plugin.gamedata.items = {"COPPER": {"en": "Copper"}}
    plugin.snapshot = {"units": 1}
    plugin.ships, plugin.frigates = [{"x": 1}], [{"y": 2}]
    plugin.history.planets["a"] = {"name": "A"}
    plugin.tables.recipes.recipes.append("not really a recipe")
    starmap._predictions[1] = {"economy": "x"}
    asyncio.run(plugin.stop())
    assert plugin.gamedata.items == {} and plugin.snapshot is None and plugin.ships == [] and plugin.frigates == []
    assert plugin.history.planets == {} and not plugin.tables.recipes.recipes and not starmap._predictions
    assert plugin.starmap._table is None
    plugin.release_memory()
    assert plugin.tables.loaded is False


def test_the_scan_chunk_defaults_to_8_mb_and_can_be_set(monkeypatch):
    """Each scan worker thread holds one buffer of CHUNK bytes: 8 MB by default (measured: half the peak RAM of 16 MB for
    ~0.4 s), NMS_SCAN_CHUNK_MB changes it within 1-64 MB, and nonsense falls back to the default."""
    from nms_connector import memory
    assert memory.CHUNK == 8 << 20
    for value, expected in (("2", 2 << 20), ("500", 64 << 20), ("0", 1 << 20), ("many", 8 << 20), ("", 8 << 20)):
        monkeypatch.setenv("NMS_SCAN_CHUNK_MB", value)
        assert memory._chunk_bytes() == expected, value
    monkeypatch.delenv("NMS_SCAN_CHUNK_MB")
    assert memory._chunk_bytes() == 8 << 20
