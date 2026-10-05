"""Tests for the No Man's Sky connector: no game, no network.

Saves are built synthetically in the real on-disk format (FEEDA1E5 chunks of LZ4
blocks around obfuscated JSON), so the decoder runs exactly as on real files.
"""

import asyncio
import json
import logging
import os
import struct
from pathlib import Path

import pytest

from nms_connector import create_plugin
from nms_connector.lz4 import LZ4Error, decompress_block
from nms_connector.saves import (SaveFile, SaveFormatError, decode_bytes, deobfuscate, find_save_dirs,
                                 list_save_files, read_save)
from nms_connector.summary import portal_code, summarize, unpack_address
from nms_connector.watcher import SaveWatcher
from viewutil import all_sections, section

# A tiny mapping in MBINCompiler's format: obfuscated -> readable.
MAPPING = {
    "F2P": "Version", "BC1": "BaseContext", "PSD": "PlayerStateData", "CSD": "CommonStateData",
    "UA1": "UniverseAddress", "RI1": "RealityIndex", "GA1": "GalacticAddress", "VX1": "VoxelX", "VY1": "VoxelY",
    "VZ1": "VoxelZ", "SSI": "SolarSystemIndex", "PI1": "PlanetIndex", "UN1": "Units", "NA1": "Nanites",
    "INV": "Inventory", "SLT": "Slots", "ID1": "Id", "AM1": "Amount", "MX1": "MaxAmount", "TY1": "Type",
    "IT1": "InventoryType", "SHO": "ShipOwnership", "NM1": "Name", "RS1": "Resource", "FN1": "Filename",
    "PPB": "PersistentPlayerBases", "BT1": "BaseType", "PBT": "PersistentBaseTypes", "OBJ": "Objects",
    "PRS": "PrimaryShip", "TPT": "TotalPlayTime",
}


def lz4_literals(data: bytes) -> bytes:
    """Encode data as a single literal-only LZ4 sequence (valid LZ4, no compression)."""
    n = len(data)
    out = bytearray([min(n, 15) << 4])
    if n >= 15:
        rest = n - 15
        while rest >= 255:
            out.append(255)
            rest -= 255
        out.append(rest)
    return bytes(out) + data


def make_save(obj: dict, chunk: int = 64) -> bytes:
    """Serialise obj to JSON and wrap it in FEEDA1E5 chunks, like the game does."""
    raw = json.dumps(obj).encode("utf-8") + b"\x00"
    out = bytearray()
    for i in range(0, len(raw), chunk):
        part = raw[i:i + chunk]
        block = lz4_literals(part)
        out += struct.pack("<IIII", 0xFEEDA1E5, len(block), len(part), 0) + block
    return bytes(out)


def obfuscated_save() -> dict:
    """A save in obfuscated form, with the shapes the real game uses."""
    return {
        "F2P": 4739,
        "CSD": {"TPT": 7300},
        "BC1": {"PSD": {
            "UA1": {"RI1": 0, "GA1": {"VX1": -384, "VY1": 2, "VZ1": -1755, "SSI": 98, "PI1": 1}},
            "UN1": 1234567, "NA1": 42, "PRS": 0,
            "INV": {"SLT": [
                {"TY1": {"IT1": "Substance"}, "ID1": "^FUEL1", "AM1": 50, "MX1": 9999},
                {"TY1": {"IT1": "Technology"}, "ID1": "^LASER", "AM1": 1, "MX1": 1},
                {"TY1": {"IT1": "Product"}, "ID1": "^CATALYST1", "AM1": 1005, "MX1": 9999},
            ]},
            "SHO": [
                {"NM1": "Star Wanderer", "RS1": {"FN1": "MODELS/COMMON/SPACECRAFT/FIGHTERS/FIGHTER_PROC.SCENE.MBIN"}, "INV": {"SLT": []}},
                {"NM1": "", "RS1": {"FN1": ""}},
            ],
            "PPB": [
                {"NM1": "Home", "GA1": 4611351810039424, "BT1": {"PBT": "HomePlanetBase"}, "OBJ": [1, 2, 3]},
                {"NM1": "Far", "GA1": "0x20B70002925E80", "BT1": {"PBT": "HomePlanetBase"}, "OBJ": []},
            ],
            "XXX": "a key the mapping does not know",
        }},
    }


def readable_save() -> dict:
    unknown = set()
    return deobfuscate(obfuscated_save(), MAPPING, unknown)


def write_mapping(path: Path) -> None:
    path.write_text(json.dumps({"libMBIN_version": "test", "Mapping": [{"Key": k, "Value": v} for k, v in MAPPING.items()]}),
                    encoding="utf-8")


# --------------------------------------------------------------------------- format


def test_lz4_literals_and_overlapping_match():
    """Literal runs (incl. the 15+255 length extension) and an overlapping match copy decode correctly."""
    data = bytes(range(256)) * 2
    assert decompress_block(lz4_literals(data), len(data)) == data
    block = bytes([0x44]) + b"abcd" + bytes([4, 0]) + bytes([0x10]) + b"x"
    assert decompress_block(block, 13) == b"abcdabcdabcdx"


@pytest.mark.parametrize("block, size", [(bytes([0x44]) + b"abcd" + bytes([9, 0]) + b"\x10x", 13),
                                         (lz4_literals(b"abc"), 4), (bytes([0xF0]), 20)])
def test_lz4_rejects_corrupt_blocks(block, size):
    """A bad offset, a wrong size or a truncated length raise LZ4Error instead of returning garbage."""
    with pytest.raises(LZ4Error):
        decompress_block(block, size)


def test_save_round_trip_and_truncation(tmp_path):
    """A multi-chunk save decodes to its JSON; a file cut mid-write is a SaveFormatError, never a crash."""
    blob = make_save(obfuscated_save())
    assert json.loads(decode_bytes(blob))["F2P"] == 4739
    with pytest.raises(SaveFormatError):
        decode_bytes(blob[:-7])
    with pytest.raises(SaveFormatError, match="magic"):
        decode_bytes(b"\x00" * 32)
    path = tmp_path / "save.hg"
    path.write_bytes(blob)
    readable, unknown = read_save(path, MAPPING)
    assert readable["BaseContext"]["PlayerStateData"]["Units"] == 1234567 and unknown == {"XXX"}


# --------------------------------------------------------------------------- summary


def test_portal_code_matches_the_game():
    """Player address and the packed base address of the same planet give the same 12 glyphs."""
    assert portal_code(1, 98, 2, -1755, -384) == "106202925E80"
    addr = unpack_address(4611351810039424)
    assert (addr["VoxelX"], addr["VoxelY"], addr["VoxelZ"], addr["SolarSystemIndex"], addr["PlanetIndex"]) == (-384, 2, -1755, 98, 1)
    assert unpack_address("0x20B70002925E80")["SolarSystemIndex"] == 0x0B7
    assert unpack_address("not hex") is None


def test_summary_extracts_companion_facts():
    """Location, currencies, inventory (tech excluded, largest first), ships (unused slots skipped) and bases."""
    snap = summarize(readable_save())
    assert snap["units"] == 1234567 and snap["play_time_s"] == 7300
    assert snap["location"]["galaxy"] == "Euclid" and snap["location"]["portal"] == "106202925E80"
    assert snap["exosuit"] == [["CATALYST1", 1005, 9999], ["FUEL1", 50, 9999]]
    assert [(s["name"], s["class"], s["primary"]) for s in snap["ships"]] == [("Star Wanderer", "Fighter", True)]
    assert [(b["name"], b["portal"], b["here"]) for b in snap["bases"]] == [("Home", "106202925E80", True), ("Far", "20B702925E80", False)]


def test_summary_survives_missing_fields():
    """An almost empty save (fields renamed by a game update) still summarises without raising."""
    snap = summarize({"Version": 1})
    assert snap["units"] is None and snap["ships"] == [] and snap["location"]["portal"] is None


# --------------------------------------------------------------------------- discovery + watcher


def test_find_save_dirs_and_slots(tmp_path):
    """Account folders with saves are found newest first; save.hg/save2.hg are slot 1, save3.hg slot 2."""
    a, b = tmp_path / "st_1", tmp_path / "st_2"
    for folder, names in ((a, ["save.hg", "save2.hg", "mf_save.hg"]), (b, ["save3.hg", "accountdata.hg"])):
        folder.mkdir()
        for name in names:
            (folder / name).write_bytes(b"x")
    os.utime(b / "save3.hg", (2_000_000_000, 2_000_000_000))
    assert find_save_dirs([tmp_path]) == [b, a]
    assert [(f.path.name, f.slot) for f in list_save_files(a)] == [("save.hg", 1), ("save2.hg", 1)]
    assert [f.slot for f in list_save_files(b)] == [2]


def _sf(name, size, mtime):
    return SaveFile(Path(name), int(name[4:-3] or 1), size, mtime)


def test_watcher_reports_settled_writes_and_measures_intervals():
    """The first poll returns the newest file; a change is reported only after it settles; intervals are recorded."""
    w = SaveWatcher(settle_s=2)
    assert [f.path.name for f in w.poll([_sf("save.hg", 10, 100), _sf("save2.hg", 10, 200)], now=1000)] == ["save2.hg"]
    assert w.poll([_sf("save.hg", 11, 400), _sf("save2.hg", 10, 200)], now=1005) == []      # just changed
    assert w.poll([_sf("save.hg", 12, 401), _sf("save2.hg", 10, 200)], now=1006) == []      # still being written
    ready = w.poll([_sf("save.hg", 12, 401), _sf("save2.hg", 10, 200)], now=1009)
    assert [f.path.name for f in ready] == ["save.hg"] and w.events[-1]["since_previous_s"] is None
    w.poll([_sf("save.hg", 12, 401), _sf("save2.hg", 13, 701)], now=1300)
    w.poll([_sf("save.hg", 12, 401), _sf("save2.hg", 13, 701)], now=1303)
    assert w.events[-1]["since_previous_s"] == 300 and w.events[-1]["slot"] == 1
    assert w.stats()["median_interval_s"] == 300


def test_watcher_ignores_breaks_in_statistics():
    """A gap over two hours (a break between sessions) does not count as a save interval."""
    w = SaveWatcher(events=[{"mtime": 0, "since_previous_s": None}, {"mtime": 600, "since_previous_s": 600},
                            {"mtime": 99999, "since_previous_s": 99399}])
    assert w.stats() == {"writes": 3, "median_interval_s": 600, "shortest_interval_s": 600, "longest_interval_s": 600}


# --------------------------------------------------------------------------- plugin


class FakeCtx:
    """The host context the 40k Assistant passes to create_plugin."""

    def __init__(self, data_dir):
        self.plugin_id, self.version, self.data_dir = "nomanssky", "0.1.0", data_dir
        self.logger = logging.getLogger("test.nms")
        self.tasks = []

    def spawn(self, coro, name):
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.append(task)
        return task

    async def run_blocking(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)


def test_plugin_reads_saves_read_only_and_builds_a_view(tmp_path, monkeypatch):
    """With a save folder and a mapping present, the connector decodes the newest save, produces a valid
    view with status/location/inventory, and leaves the save folder byte-for-byte untouched."""
    saves_dir = tmp_path / "NMS" / "st_1"
    saves_dir.mkdir(parents=True)
    (saves_dir / "save.hg").write_bytes(make_save(obfuscated_save()))
    before = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in saves_dir.iterdir()}
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "NMS"))
    data = tmp_path / "data"
    data.mkdir()
    write_mapping(data / "mapping.json")
    monkeypatch.setattr("nms_connector.plugin.download_mapping", lambda dest: pytest.fail("must not download"))

    async def scenario():
        plugin = create_plugin(FakeCtx(data))
        await plugin._tick()
        view = plugin.view()
        result = await plugin.action("rescan", {})
        await plugin.stop()
        return plugin, view, result

    plugin, view, result = asyncio.run(scenario())
    main = section(view, type="tabs", id="main")
    assert [t["label"] for t in main["tabs"]] == ["Overview", "Systems", "Inventory", "Ships & bases", "Settlements", "Saves & source"]
    titles = [s.get("title") for s in all_sections(view["sections"])]
    assert "Status" in titles and "Location (at the last save)" in titles and "Exosuit inventory" in titles
    assert "Status" in [s.get("title") for s in main["tabs"][0]["sections"]]
    location = section(view, "Location (at the last save)")
    assert {"label": "Portal address", "value": "106202925E80"} in location["items"]
    assert any("unknown to the current mapping" in s.get("text", "") for s in view["sections"])
    assert result["ok"] is True and plugin.snapshot is None
    assert {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in saves_dir.iterdir()} == before
    assert (data / "save_events.json").exists()


def test_plugin_without_saves_or_mapping_explains_itself(tmp_path, monkeypatch):
    """No save folder and a failed mapping download produce warnings in the view, not an exception."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))

    def offline(dest):
        raise OSError("offline")
    monkeypatch.setattr("nms_connector.plugin.download_mapping", offline)

    async def scenario():
        plugin = create_plugin(FakeCtx(tmp_path / "data"))
        await plugin._tick()
        return plugin.view()

    view = asyncio.run(scenario())
    texts = " ".join(s.get("text", "") for s in view["sections"])
    assert "No No Man's Sky saves found" in texts and "offline" in texts


def test_clicking_a_visited_system_selects_it_and_focuses_the_map(tmp_path, monkeypatch):
    """open_system (a row of the visited-systems table) remembers the system and asks the page to show the
    system map; an unparsable key is refused without changing the selection."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))

    async def scenario():
        plugin = create_plugin(FakeCtx(tmp_path / "data"))
        ok = await plugin.action("open_system", {"key": "620002925e80"})
        bad = await plugin.action("open_system", {"key": "not hex"})
        return plugin, ok, bad

    plugin, ok, bad = asyncio.run(scenario())
    assert ok == {"ok": True, "focus": "system-map"} and bad["ok"] is False
    assert plugin.selected_system == 0x620002925E80


def test_manifest_fits_the_registry_rules():
    """The registry and the app refuse a description over 300 characters (0.4.0 was unpublishable because of
    it); the tag the registry pins must be v<version>, so the version must be plain semver."""
    import re
    manifest = json.loads((Path(__file__).resolve().parent.parent / "strategicum-plugin.json").read_text(encoding="utf-8"))
    assert 0 < len(manifest["description"]) <= 300
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])


def test_icons_are_prepared_for_the_storage_containers_too():
    """Seen 2026-10-04: every item in the storage containers had its name but no icon - their rows were not
    among the items whose icons are converted. Now they are, once each."""
    from nms_connector.plugin import _snapshot_item_ids
    snap = {"exosuit": [["FUEL1", 1, 1]], "exosuit_cargo": [], "freighter": {"inventory": []}, "ships": [],
            "storage": [{"rows": [["CAVE2", 5, 250], ["FUEL1", 2, 250]]}, {"rows": []}]}
    assert _snapshot_item_ids(snap) == ["FUEL1", "CAVE2"]


def test_the_current_mission_is_shown_as_the_games_text(tmp_path):
    """The Overview showed the mission id (ACT1_STEP10). The game keeps the mission's text under
    UI_CORE_<id>_DESC: that is shown (shortened, with the id), the id alone when no text is known."""
    from nms_connector.summary import mission_text_keys
    assert mission_text_keys("ACT1_STEP10")[0] == "UI_CORE_ACT1_STEP10_DESC" and mission_text_keys(None) == []
    plugin = create_plugin(FakeCtx(tmp_path))
    long = "Apollo has asked me to upgrade my equipment by obtaining blueprints from a multitool technology trader. " * 3
    plugin.gamedata.text = lambda key: {"en": long, "local": long} if key == "UI_CORE_ACT1_STEP10_DESC" else None
    text = plugin.describe.mission("ACT1_STEP10")
    assert text.startswith("Apollo has asked me") and text.endswith("... (ACT1_STEP10)") and len(text) < 240
    assert plugin.describe.mission("UNKNOWN_STEP") == "UNKNOWN_STEP" and plugin.describe.mission(None) == "none"


def test_the_overview_names_the_primary_ship_and_the_settlements(tmp_path):
    """The Overview's fleet block leads with the primary ship and its warp range estimate and a line per
    settlement (construction, waiting decision) - the details live in Ships & bases and Settlements."""
    plugin = create_plugin(FakeCtx(tmp_path))
    assert plugin.describe.primary_ship() == "none" and plugin.describe.settlements() == "none"
    plugin.ships = [{"name": "Bang", "type": "Fighter", "class": "C", "primary": True, "stats": {"hyperdrive": 0.0},
                     "technology": [{"id": "HYPERDRIVE"}, {"id": "UP_HYP4#1"}, {"id": "HDRIVEBOOST1"}]}]
    assert plugin.describe.primary_ship() == "Bang (Fighter, class C) - warp range ~320-365 ly, red stars"
    plugin.settlements = [{"name": "Kay City", "building": "Farm", "pending": "StrangerVisit"}, {"name": "Rest", "pending": "None"}]
    assert plugin.describe.settlements() == "Kay City: Farm in construction, a decision is waiting; Rest (see Settlements)"


def test_the_plugin_brings_its_persona_and_answers_chat_questions_from_the_save(tmp_path):
    """App 3.9.0 stores the persona the plugin brings ("No Man's Sky Plugin Persona", answering from [GAME DATA])
    and asks chat_context before each of its replies: the answer carries status lines and the named item's
    totals from the snapshot."""
    plugin = create_plugin(FakeCtx(tmp_path))
    persona, = plugin.personas()
    assert persona["slug"] == "companion" and persona["name"] == "No Man's Sky Plugin Persona"
    assert "[GAME DATA: No Man's Sky]" in persona["system_prompt"] and persona["temperature"] == 0.3
    assert plugin.chat_context("how much copper")["text"] == "No save has been read yet, so there is no game data."
    plugin.snapshot = {"exosuit": [["YELLOW2", 5, 250]], "exosuit_cargo": [], "ships": [], "storage": [],
                       "freighter": {"name": None, "inventory": []}, "bases": [], "saved_at": None, "units": 1,
                       "nanites": 2, "quicksilver": 3, "location": {"galaxy": "Euclid", "portal": "x"}, "current_mission": None}
    plugin.gamedata.lookup = lambda item_id: {"en": "Copper", "local": "Kupfer"} if item_id == "YELLOW2" else None
    out = plugin.chat_context("how much copper do I have")
    assert out["title"] == "No Man's Sky"
    assert "Units 1, Nanites 2, Quicksilver 3" in out["text"] and "[YELLOW2]: 5 in total - Exosuit: 5" in out["text"]


def test_settlement_and_economy_questions_get_their_details(tmp_path):
    """"How is my settlement doing?" got one line that contradicted the timer ("Farm in construction" while the
    timer said done). A settlement question now gets population, production, the waiting decision and the
    construction as finished; an economy question the nearest systems of that economy (predicted ones marked)."""
    plugin = create_plugin(FakeCtx(tmp_path))
    plugin.settlements = [{"name": "Kay City", "population": 20, "race": "Explorers", "seed": 1, "production": [],
                           "pending": "StrangerVisit", "last_judgement": 0, "building": "Farm", "perks": ["a"]}]
    plugin.timers = [{"key": "settlement.kay.27", "label": "Kay City: Farm built", "ends_at": 100.0, "started_at": 1.0}]
    lines = plugin.companion.settlement_lines({"how", "is", "my", "settlement"}, 200.0)
    assert lines[0] == "Settlement Kay City: population 20 (Explorers)"
    assert "  a decision is waiting: Stranger visit" in lines and "  construction: Kay City: Farm built - finished at" in lines[2]
    assert plugin.companion.settlement_lines({"copper"}, 200.0) == []
    assert plugin.describe.settlements().startswith("Kay City: Farm finished, a decision is waiting")


def test_the_persona_asks_for_a_codex_library_and_web_search_and_answers_equipment_questions(tmp_path):
    """The persona carries a setup (app 3.10.0): the plugin page asks for a Codex library (suggested "No Man's Sky")
    and web search when the model can; its prompt keeps the player's numbers to the game data. A question about
    the multi-tool lists its installed technology with what each part does; other questions get no equipment."""
    from nms_connector import equipment
    from test_equipment import Texts, save
    plugin = create_plugin(FakeCtx(tmp_path))
    persona, = plugin.personas()
    assert persona["setup"]["knowledge"]["suggest"] == "No Man's Sky" and persona["setup"]["web_search"]["ask"]
    assert "Codex excerpts or web search" in persona["system_prompt"]
    plugin.equipment = equipment.Equipment.from_save(save())

    class Named(Texts):
        def name(self, item_id):
            return item_id.split("#")[0]

    lines = plugin.companion.equipment_lines({"which", "upgrades", "multitool"}, Named())
    assert lines[0] == ("Multi-tool Quantum Kay Needler (class A, in your hand): UP_LASER1 (Mining Speed +5-10 %, "
                        "Heat Dispersion +5-15 %); TERRAINEDITOR")
    assert len(lines) == 3 and "exact values are not stored" in lines[-1]
    assert plugin.companion.equipment_lines({"how", "much", "copper"}, Named()) == []


def test_game_tables_load_once_per_build_and_report_fallbacks():
    """GameTables reads every table of a build once (again after an update) and names each table that fell back to
    built-in values; the views use the fallbacks until then."""
    from nms_connector import ships
    from nms_connector.tables import GameTables
    tables = GameTables()
    assert tables.needs_load(None) and tables.ship_ranges is ships.FALLBACK and tables.trait_names == {}
    warnings = tables.load(None)
    assert not tables.needs_load(None) and len(warnings) == 5 and all("not found" in w for w in warnings)

    class Install:
        build_id = "new"
    assert tables.needs_load(Install())


def test_a_trade_goods_question_gets_the_kinds_with_value_and_buyer_and_no_equipment(tmp_path):
    """The persona's data for "what kind of trade goods do I have the most aboard my ship" leads with the kinds of
    the ship (base value, the economies that need them, the nearest known one); naming the ship alone does not
    pull in its technology (that ran the block over the app's 8,000 characters)."""
    plugin = create_plugin(FakeCtx(tmp_path))
    plugin.snapshot = {"exosuit": [], "exosuit_cargo": [], "storage": [], "bases": [], "saved_at": None, "units": 1,
                       "nanites": 2, "quicksilver": 3, "location": {"galaxy": "Euclid", "portal": "x"}, "current_mission": None,
                       "ships": [{"name": "Raptor", "primary": True, "inventory": [["TRA_TECH4", 78, 100], ["TRA_TECH2", 69, 100]]}],
                       "freighter": {"name": None, "inventory": []}}
    plugin.ships = [{"name": "Raptor", "type": "Shuttle", "class": "A", "primary": True, "stats": {}, "index": 0,
                     "technology": [{"id": "HYPERDRIVE", "charge": 1, "max": 1}]}]
    items = {"TRA_TECH4": {"en": "Autonomous Positioning Unit", "value": 30000}, "TRA_TECH2": {"en": "Welding Soap", "value": 6000}}
    plugin.gamedata.lookup = lambda item_id: items.get(item_id)
    text = plugin.chat_context("what kind of trade goods do i have the most aboard my active ship?")["text"]
    assert "Trade goods by kind in Starship 'Raptor' (primary)" in text
    assert "- Technology: 147 units (Autonomous Positioning Unit 78, Welding Soap 69); base value 2,754,000 units" in text
    assert "needed by" in text and "Power" in text
    assert "Starship Raptor (primary): " not in text            # no equipment lines for a cargo question
    assert plugin.companion.equipment_lines({"which", "upgrades", "ship"}, plugin.context().texts) != []
