"""Tests for the export and import of the plugin's data (transfer.py, the page's Transfer tab and the
connector's two actions): the merge rules, the refusals of an untrusted archive, and a round trip."""

import json
import zipfile

from nms_connector import page, transfer

NOW = "2026-10-14T12:00:00"


def write_data_dir(root, *, planets=1, build="100", with_cache=True):
    """A data dir as the plugin leaves it: a history, the measured saves, settings and the item cache."""
    root.mkdir(parents=True, exist_ok=True)
    history = {"version": 2, "planets": {f"p{i}": {"ua": i, "name": f"P{i}", "first_seen": "2026-10-01T00:00:00",
                                                   "last_seen": "2026-10-02T00:00:00"} for i in range(planets)},
               "scans": [{"at": "2026-10-02T00:00:00", "planets": planets}],
               "economies": {"62": {"economy": "Mining", "read_at": "2026-10-02T00:00:00"}},
               "system_names": {"62": "Delta Sol"}, "star_fixes": [], "guilds": {}}
    (root / "planet_history.json").write_text(json.dumps(history), encoding="utf-8")
    (root / "save_events.json").write_text(json.dumps([{"at": NOW, "file": "save.hg", "mtime": 1.0, "slot": 1,
                                                        "size": 10, "since_previous_s": 60}]), encoding="utf-8")
    (root / "settings.json").write_text(json.dumps({"codeword": "Atlas", "single_context": True}), encoding="utf-8")
    if with_cache:
        (root / "gamedata").mkdir(exist_ok=True)
        (root / "gamedata" / "items.json").write_text(json.dumps({"build_id": build, "items": {}}), encoding="utf-8")
        (root / "assets").mkdir(exist_ok=True)
        (root / "assets" / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    # Files the *host* owns, never the connector's to move.
    (root / ".stc-data.json").write_text("{}", encoding="utf-8")
    (root / "codex_stamp.json").write_text("{}", encoding="utf-8")
    (root / "planet_history.json.bak").write_text("{}", encoding="utf-8")
    return root


def mover(root, host="plugin", build="100"):
    return transfer.DataTransfer(root, host=host, plugin_version="0.15.0-beta.5", game_build=build)


def test_an_export_holds_the_connectors_files_and_none_of_the_hosts(tmp_path):
    """The archive carries what cannot be read back out of the game, plus the rebuildable caches - but not
    the host's own bookkeeping (.stc-data.json, codex_stamp.json) or the history's .bak, which describe the
    host that wrote them and would lie in the other one."""
    data = write_data_dir(tmp_path / "data")
    done = mover(data).export(str(tmp_path / "out"), NOW)
    assert done["files"] == 5 and done["bytes"] > 0
    with zipfile.ZipFile(done["path"]) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read(transfer.MANIFEST))
    assert names == {transfer.MANIFEST, "planet_history.json", "save_events.json", "settings.json",
                     "gamedata/items.json", "assets/icon.png"}
    assert manifest["format"] == 1 and manifest["host"] == "plugin" and manifest["game_build"] == "100"
    assert manifest["plugin_version"] == "0.15.0-beta.5" and manifest["created_at"] == NOW
    # Two exports on one day do not overwrite each other.
    again = mover(data).export(str(tmp_path / "out"), NOW)
    assert again["path"].endswith("-2.zip")


def test_a_merge_keeps_every_local_record_and_adds_the_others(tmp_path):
    """The merge rules, as pure functions: the newer reading of a planet wins but its earliest sighting and
    all its former names are kept, a planet confirmed on either host stays confirmed, economies take the
    newer reading, and names, guilds and fixes fill gaps only - the local host is the one being played on."""
    local = {"version": 2,
             "planets": {"a": {"name": "A", "first_seen": "2026-10-05T00:00:00", "last_seen": "2026-10-09T00:00:00",
                               "confirmed": False, "previous_names": ["Old A"], "biome": "LUSH"}},
             "scans": [{"at": "2026-10-09T00:00:00"}], "economies": {"62": {"economy": "Mining", "read_at": "2026-10-09T00:00:00"}},
             "system_names": {"62": "Delta Sol"}, "guilds": {"1, 2, 3": {"guild": "merchants"}}, "star_fixes": []}
    incoming = {"version": 2,
                "planets": {"a": {"name": "A", "first_seen": "2026-10-01T00:00:00", "last_seen": "2026-10-03T00:00:00",
                                  "confirmed": True, "previous_names": ["First A"], "biome": "TOXIC"},
                            "b": {"name": "B", "first_seen": "2026-10-02T00:00:00", "last_seen": "2026-10-02T00:00:00"}},
                "scans": [{"at": "2026-10-03T00:00:00"}],
                "economies": {"62": {"economy": "Trading", "read_at": "2026-10-11T00:00:00"},
                              "63": {"economy": "Fusion", "read_at": "2026-10-01T00:00:00"}},
                "system_names": {"62": "Other name", "99": "Kayana"},
                "guilds": {"1, 2, 3": {"guild": "explorers"}, "4, 5, 6": {"guild": "mercenaries"}},
                "star_fixes": [{"id": 1, "system": "62", "position": [0, 0, 0]}]}
    merged = transfer.merge_history(local, incoming)

    planet = merged["planets"]["a"]
    assert planet["biome"] == "LUSH"                      # the newer reading (local) wins
    assert planet["first_seen"] == "2026-10-01T00:00:00"  # but you saw it earlier on the other host
    assert planet["previous_names"] == ["Old A", "First A"]
    assert planet["confirmed"] is True                    # confirmed on the other host cannot un-happen
    assert merged["planets"]["b"]["name"] == "B"          # a planet only the archive knows is added

    assert merged["economies"]["62"]["economy"] == "Trading"   # read later on the other host
    assert merged["economies"]["63"]["economy"] == "Fusion"
    assert merged["system_names"] == {"62": "Delta Sol", "99": "Kayana"}
    assert merged["guilds"]["1, 2, 3"]["guild"] == "merchants" and "4, 5, 6" in merged["guilds"]
    assert [s["at"] for s in merged["scans"]] == ["2026-10-03T00:00:00", "2026-10-09T00:00:00"]
    assert merged["star_fixes"] == [{"id": 1, "system": "62", "position": [0, 0, 0]}]

    # A local fix of that system keeps it: one fix per system, as the naming action enforces.
    local["star_fixes"] = [{"id": 7, "system": "62", "position": [1, 1, 1]}]
    assert transfer.merge_history(local, incoming)["star_fixes"] == local["star_fixes"]
    # A fix of another system is appended with an id that is free here.
    incoming["star_fixes"] = [{"id": 7, "system": "99", "position": [2, 2, 2]}]
    assert [f["id"] for f in transfer.merge_history(local, incoming)["star_fixes"]] == [7, 8]


def test_the_same_star_fix_on_both_hosts_is_not_doubled(tmp_path):
    """A fix's id is per host, so importing a host's own exported fixes back (or two hosts that recorded the
    same stars) would double every one of them - found on the real data, where 6 fixes became 12. The same
    position, or the same named system, is the same fix."""
    fixes = [{"id": 1, "system": "62", "position": [1.0, 2.0, 3.0]},
             {"id": 2, "system": None, "position": [4.0, 5.0, 6.0]}]
    history = {"planets": {}, "star_fixes": fixes}
    assert transfer.merge_history(history, {"planets": {}, "star_fixes": [dict(f) for f in fixes]})["star_fixes"] == fixes
    # A rounding difference in the last digits is still the same star, a real new one is added.
    nearly = [{"id": 9, "system": None, "position": [4.00000001, 5.0, 6.0]},
              {"id": 9, "system": None, "position": [7.0, 8.0, 9.0]}]
    merged = transfer.merge_history(history, {"planets": {}, "star_fixes": nearly})["star_fixes"]
    assert [f["id"] for f in merged] == [1, 2, 3] and merged[-1]["position"] == [7.0, 8.0, 9.0]


def test_the_scan_log_and_the_save_events_stay_capped(tmp_path):
    """Both are rolling logs. Merging two hosts' logs must not grow the file without bound, and the same
    save write (same file and mtime) recorded on both hosts counts once."""
    local = {"planets": {}, "scans": [{"at": f"2026-10-{d:02d}T00:00:00"} for d in range(1, 30)]}
    incoming = {"planets": {}, "scans": [{"at": f"2026-11-{d:02d}T00:00:00"} for d in range(1, 30)]}
    scans = transfer.merge_history(local, incoming)["scans"]
    assert len(scans) == transfer.MAX_SCANS and scans[-1]["at"] == "2026-11-29T00:00:00"

    one = {"file": "save.hg", "mtime": 5.0, "at": "a"}
    events = transfer.merge_events([one, {"file": "save.hg", "mtime": 7.0}], [dict(one), {"file": "save2.hg", "mtime": 6.0}])
    assert [(e["file"], e["mtime"]) for e in events] == [("save.hg", 5.0), ("save2.hg", 6.0), ("save.hg", 7.0)]
    assert len(transfer.merge_events([{"file": "s", "mtime": i} for i in range(400)], [])) == transfer.MAX_EVENTS


def test_an_archive_member_outside_the_plugins_own_files_is_refused(tmp_path):
    """The archive may come from anywhere, so its member names are a whitelist, not something to interpret:
    an absolute path, a parent step, a Windows drive or a file the plugin does not own are all refused."""
    assert transfer.member_problem("planet_history.json", 10) is None
    assert transfer.member_problem("assets/icon.png", 10) is None
    assert transfer.member_problem("gamedata/items.json", 10) is None
    for name in ("/etc/passwd", "../outside.json", "..\\outside.json", "C:/Windows/system.ini",
                 "assets/sub/icon.png", "evil.exe", "src/main.py", "assets/", "./planet_history.json"):
        assert transfer.member_problem(name, 10), name
    assert transfer.member_problem("assets/icon.png", transfer.MAX_MEMBER_BYTES + 1)


def test_a_damaged_or_foreign_archive_changes_nothing(tmp_path):
    """Every refusal happens while reading, before the first write: a zip that is not one, one without a
    manifest, a format this plugin cannot read, a bad member and damaged JSON all leave the data dir as it
    was - checked by comparing the history file before and after."""
    import pytest

    data = write_data_dir(tmp_path / "data")
    before = (data / "planet_history.json").read_bytes()
    move = mover(data)

    def refuses(path, message):
        with pytest.raises(ValueError) as caught:
            move.apply(str(path), transfer.MERGE, NOW)
        assert message in str(caught.value), caught.value
        assert (data / "planet_history.json").read_bytes() == before

    refuses(tmp_path / "missing.zip", "does not exist")

    not_a_zip = tmp_path / "not.zip"
    not_a_zip.write_bytes(b"this is not a zip")
    refuses(not_a_zip, "not a readable zip file")

    no_manifest = tmp_path / "bare.zip"
    with zipfile.ZipFile(no_manifest, "w") as archive:
        archive.writestr("planet_history.json", "{}")
    refuses(no_manifest, "no manifest.json")

    future = tmp_path / "future.zip"
    with zipfile.ZipFile(future, "w") as archive:
        archive.writestr(transfer.MANIFEST, json.dumps({"format": 99, "files": {}}))
    refuses(future, "this plugin reads 1")

    smuggled = tmp_path / "smuggled.zip"
    with zipfile.ZipFile(smuggled, "w") as archive:
        archive.writestr(transfer.MANIFEST, json.dumps({"format": 1, "files": {}}))
        archive.writestr("../../evil.json", "{}")
    refuses(smuggled, "not a plain relative path")

    damaged = tmp_path / "damaged.zip"
    with zipfile.ZipFile(damaged, "w") as archive:
        archive.writestr(transfer.MANIFEST, json.dumps({"format": 1, "files": {}}))
        archive.writestr("planet_history.json", "{not json")
    refuses(damaged, "is damaged")
    assert not (data / transfer.DataTransfer.BACKUP_DIR).exists()      # no backup was written either


def test_a_look_into_an_archive_writes_nothing_and_says_what_each_mode_would_do(tmp_path):
    """"Only look into it" is the default of the import form: it reports who wrote the archive, what it
    holds and, per file, what merging or replacing would do - without touching anything."""
    source = write_data_dir(tmp_path / "source", planets=3, build="200")
    archive = mover(source, host="standalone", build="200").export(str(tmp_path / "out"), NOW)["path"]

    here = write_data_dir(tmp_path / "here", planets=1, build="100")
    before = sorted(p.name for p in here.iterdir())
    looked = mover(here).inspect(archive, transfer.MERGE)
    assert looked["manifest"]["host"] == "standalone"
    assert looked["counts"]["planets"] == 3 and looked["mine"]["planets"] == 1
    assert looked["plan"]["planet_history.json"] == "merged"
    assert looked["plan"]["settings.json"].startswith("kept")
    assert "2 files replaced" in looked["plan"]["gamedata/ + assets/"]     # the archive is a newer game build
    assert sorted(p.name for p in here.iterdir()) == before

    # Replacing says so for every file, and the caches are always taken.
    replacing = mover(here).inspect(archive, transfer.REPLACE)
    assert replacing["plan"]["settings.json"] == "replaced" and replacing["plan"]["planet_history.json"] == "replaced"
    # The other way round: an archive from an older game build leaves the newer local caches alone.
    old = mover(here, build="100").inspect(mover(write_data_dir(tmp_path / "old", build="50"), build="50")
                                           .export(str(tmp_path / "out2"), NOW)["path"], transfer.MERGE)
    assert "skipped" in old["plan"]["gamedata/ + assets/"]


def test_caches_are_taken_only_when_they_can_be_newer():
    """The item and icon caches are rebuildable from the game files, but a machine without the game cannot
    rebuild them - so they travel, and a merge takes them only when the archive's game build is newer (or
    nothing is here to keep). Builds are numeric strings, which do not compare as numbers by themselves."""
    assert transfer.take_caches("200", "100", True) is True
    assert transfer.take_caches("90", "100", True) is False
    assert transfer.take_caches("100", "100", True) is False
    assert transfer.take_caches("9999999", "25732212", True) is False     # compared as numbers, not text
    assert transfer.take_caches(None, "100", True) is False
    assert transfer.take_caches("100", None, True) is True
    assert transfer.take_caches(None, None, False) is True                # nothing here yet: take them


def test_a_round_trip_moves_the_data_and_keeps_a_backup(tmp_path):
    """Export on one host, import on the other: the merge adds the archive's planets to the local ones,
    the local settings are untouched, and the data that was here is zipped aside first - the whole point
    of the feature, end to end on real files."""
    source = write_data_dir(tmp_path / "source", planets=3, build="100")
    archive = mover(source, host="standalone").export(str(tmp_path / "out"), NOW)["path"]

    here = write_data_dir(tmp_path / "here", planets=1, build="100")
    (here / "settings.json").write_text(json.dumps({"codeword": "Nada", "single_context": False}), encoding="utf-8")
    done = mover(here).apply(archive, transfer.MERGE, NOW)

    history = json.loads((here / "planet_history.json").read_text(encoding="utf-8"))
    assert sorted(history["planets"]) == ["p0", "p1", "p2"]        # 1 local + 3 from the archive, p0 shared
    assert done["counts"]["planets"] == 3 and done["mine"]["planets"] == 3
    assert json.loads((here / "settings.json").read_text(encoding="utf-8"))["codeword"] == "Nada"
    backup = json.loads(json.dumps(done))["backup"]
    with zipfile.ZipFile(backup) as saved:
        assert "planet_history.json" in saved.namelist()
    assert json.loads(zipfile.ZipFile(backup).read("planet_history.json"))["planets"].keys() == {"p0"}

    # Replacing takes the archive's settings too.
    replaced = mover(here).apply(archive, transfer.REPLACE, NOW)
    assert json.loads((here / "settings.json").read_text(encoding="utf-8"))["codeword"] == "Atlas"
    assert replaced["plan"]["settings.json"] == "replaced"


def test_the_page_reports_the_last_transfer(tmp_path):
    """The Transfer tab shows what the last export, look or import did, from the state the connector kept -
    pure, so the report is testable without a zip. Nothing recorded yet shows no result sections."""
    assert page.transfer_result_sections(None) == []
    export = page.transfer_result_sections({"kind": "export", "path": "C:/out/nms-data.zip", "files": 5,
                                            "bytes": 2 * 2**20, "at": NOW})
    assert export[0]["title"] == "Last export"
    assert {i["label"]: i["value"] for i in export[0]["items"]}["Size"] == "2.0 MB"

    state = {"kind": "inspect", "mode": "merge", "path": "a.zip",
             "manifest": {"host": "standalone", "plugin_version": "0.15.0", "created_at": NOW,
                          "game_build": "200", "files": {"planet_history.json": 10}},
             "plan": {"planet_history.json": "merged"}, "counts": {"planets": 3}, "mine": {"planets": 1}}
    looked = page.transfer_result_sections(state)
    assert looked[0]["title"] == "What that archive holds"
    assert "standalone" in {i["label"]: i["value"] for i in looked[0]["items"]}["Written by"]
    assert looked[1]["rows"] == [["planet_history.json", "merged"]]
    assert looked[2]["rows"] == [["planets", "3", "1"]] and looked[2]["columns"][-1] == "Here now"

    imported = page.transfer_result_sections({**state, "kind": "merge", "backup": "b.zip"})
    assert imported[0]["title"] == "Last import (merged)"
    assert {i["label"] for i in imported[0]["items"]} >= {"Your data backed up to"}
    assert imported[2]["columns"][-1] == "Here after the import"


def test_the_transfer_actions_check_their_input(tmp_path, monkeypatch):
    """Both actions take untrusted form values: an unknown mode or an empty path answers ok False and writes
    nothing, and a failed export reports the reason instead of raising into the host."""
    from nms_connector import create_plugin
    from test_connector import FakeCtx

    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    assert plugin._import_data({"path": "x.zip", "mode": "delete-everything"})["ok"] is False
    assert plugin._import_data({"mode": transfer.MERGE})["ok"] is False
    assert plugin._import_data({"path": "  ", "mode": transfer.INSPECT})["ok"] is False
    assert plugin.transfer_state is None
    missing = plugin._import_data({"path": str(tmp_path / "nope.zip"), "mode": transfer.INSPECT})
    assert missing["ok"] is False and "does not exist" in missing["message"]

    done = plugin._export_data({"folder": str(tmp_path / "out")})
    assert done["ok"] is True and done["focus"] == page.TRANSFER_RESULT_ID
    assert plugin.transfer_state["kind"] == "export"
    archive = plugin.transfer_state["path"]

    looked = plugin._import_data({"path": archive, "mode": transfer.INSPECT})
    assert looked["ok"] is True and "Nothing was changed" in looked["message"]
    assert plugin.transfer_state["manifest"]["host"] == "plugin"      # the app's context names no host
    sections = plugin.page.transfer_sections()
    assert [s.get("id") for s in sections[:3]] == [None, page.TRANSFER_EXPORT_ID, page.TRANSFER_IMPORT_ID]
    assert sections[3]["id"] == page.TRANSFER_RESULT_ID      # the look's report, under the two forms
    modes = [o["value"] for o in sections[2]["fields"][1]["options"]]
    assert modes == [transfer.INSPECT, transfer.MERGE, transfer.REPLACE]

    imported = plugin._import_data({"path": archive, "mode": transfer.MERGE})
    assert imported["ok"] is True and "imported (merge)" in imported["message"]
    assert plugin.transfer_state["kind"] == "merge"
