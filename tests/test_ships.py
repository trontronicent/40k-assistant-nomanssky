"""Tests for the ships tab: warp-range tables from the game's technology tables, ships from the save, the view."""

import struct

from nms_connector import mbin, ships

MARK = mbin.MARK


def _table(records: list[bytes], record_size: int, lists: list[list[bytes]], list_at: int) -> bytes:
    """A root list of fixed-size records, each with one list (header at `list_at`) whose data follows them."""
    root, start = 0x10, 0x20
    end = start + record_size * len(records)
    data = bytearray(end + sum(len(b) for items in lists for b in items) + 0x10)
    struct.pack_into("<QI4s", data, root, start - root, len(records), MARK)
    tail = end
    for k, (record, items) in enumerate(zip(records, lists)):
        p = start + k * record_size
        data[p:p + len(record)] = record
        struct.pack_into("<QI4s", data, p + list_at, tail - (p + list_at), len(items), MARK)
        for item in items:
            data[tail:tail + len(item)] = item
            tail += len(item)
    return bytes(data)


def tech_table(hyperdrive=100.0) -> bytes:
    def record(tid):
        r = bytearray(0x2E0)
        r[ships.TECH_ID_AT:ships.TECH_ID_AT + len(tid)] = tid.encode()
        return bytes(r)
    bonus = lambda value, stat: struct.pack("<fiI", value, 1, stat)       # noqa: E731
    return _table([record("HYPERDRIVE"), record("HDRIVEBOOST1"), record("SHIPJUMP1")], 0x2E0,
                  [[bonus(1.0, 148), bonus(hyperdrive, ships.JUMP_DISTANCE)], [bonus(1.0, 148)], [bonus(100.0, 158)]],
                  ships.TECH_BONUSES_AT)


def proc_table() -> bytes:
    def record(pid):
        r = bytearray(0x290)
        r[ships.PROC_ID_AT:ships.PROC_ID_AT + len(pid)] = pid.encode()
        return bytes(r)
    level = lambda stat, vmax, vmin: struct.pack("<Iff", stat, vmax, vmin) + b"\0" * 8     # noqa: E731
    return _table([record("UP_HYP4"), record("UP_SHL1")], 0x290,
                  [[level(ships.JUMP_DISTANCE, 265.0, 220.0), level(150, 1.0, 1.0)], [level(143, 10.0, 5.0)]],
                  ships.PROC_LEVELS_AT)


def test_jump_distance_bonuses_are_read_from_the_technology_tables():
    """HYPERDRIVE gives 100 ly and UP_HYP4 220-265 ly (build 25625620); other stats are ignored. A table where
    HYPERDRIVE does not give 100 ly (moved layout) is refused, so the measured values are used instead."""
    tables = ships.parse_tables(tech_table(), proc_table())
    assert tables["fixed"] == {"HYPERDRIVE": 100.0} and tables["procedural"] == {"UP_HYP4": (220.0, 265.0)}
    assert ships.parse_tables(tech_table(hyperdrive=7.0), proc_table()) is None
    assert ships.parse_tables(b"short", b"short") is None
    fallback = ships.load_tables(None)
    assert fallback["procedural"]["UP_HYP4"] == (220.0, 265.0) and "not found" in fallback["error"]


def slot(tid, amount=-1, maximum=100):
    return {"Type": {"InventoryType": "Technology"}, "Id": f"^{tid}", "Amount": amount, "MaxAmount": maximum}


def ship(name, filename, cls, stats, tech, slots=15):
    return {"Name": name, "Resource": {"Filename": filename},
            "Inventory": {"Class": {"InventoryClass": cls}, "ValidSlotIndices": [0] * slots,
                          "BaseStatValues": [{"BaseStatID": f"^SHIP_{k}", "Value": v} for k, v in stats.items()],
                          "Slots": [{"Type": {"InventoryType": "Product"}, "Id": "^FUEL1"}]},
            "Inventory_TechOnly": {"ValidSlotIndices": [0] * 16, "Slots": tech}, "Inventory_Cargo": {}}


def save():
    """Kay's ships on 2026-10-04 (trimmed): a C-class fighter with a hyperdrive and an S-class upgrade (primary),
    an explorer with a +44 % hyperdrive bonus and damaged slots, and an unused ownership slot."""
    return {"BaseContext": {"PlayerStateData": {"PrimaryShip": 2, "ShipOwnership": [
        ship("", "MODELS/COMMON/SPACECRAFT/SCIENTIFIC/SCIENTIFIC_PROC.SCENE.MBIN", "B", {"HYPERDRIVE": 44.28},
             [slot("HYPERDRIVE", 0, 120), slot("SHIPSLOT_DMG3", 1), slot("SHIPSLOT_DMG4", 1)]),
        {"Name": "", "Resource": {"Filename": ""}},
        ship("Bang", "MODELS/COMMON/SPACECRAFT/FIGHTERS/FIGHTER_PROC.SCENE.MBIN", "C", {"DAMAGE": 9.478, "HYPERDRIVE": 0.0},
             [slot("HYPERDRIVE", 96, 120), slot("UP_HYP4#66014"), slot("HDRIVEBOOST1", 50), slot("HDRIVEBOOST2"),
              slot("SHIPJUMP1", 132, 200)]),
    ]}}}


def test_ships_are_read_with_their_technology_primary_first():
    """Unused ownership slots are skipped; type comes from the model, class and base stats from the inventory,
    technology from both inventories (not the products in the general one)."""
    items = ships.ships_from_save(save())
    assert [s["name"] for s in items] == ["Bang", ""]
    bang = items[0]
    assert bang["primary"] and bang["type"] == "Fighter" and bang["class"] == "C" and bang["stats"]["damage"] == 9.5
    assert [t["id"] for t in bang["technology"]][:2] == ["HYPERDRIVE", "UP_HYP4#66014"]
    assert ships.damaged_slots(items[1]) == 2


def test_warp_range_adds_drive_and_upgrades_and_the_ships_bonus():
    """Fighter: 100 ly drive + UP_HYP4 220-265 ly = 320-365 ly; the explorer's own +44.3 % makes its 100 ly drive
    reach ~144 ly. HDRIVEBOOST1/2 add no range but open red and green stars. No drive: no range."""
    tables = dict(ships.FALLBACK)
    bang, explorer = ships.ships_from_save(save())
    est = ships.warp_range(bang, tables)
    assert (est["low"], est["high"], est["colours"]) == (320, 365, ["red", "green"])
    assert ships.range_text(est) == "~320-365 ly"
    assert ships.range_text(ships.warp_range(explorer, tables)) == "~144 ly"
    no_drive = dict(explorer, technology=[])
    assert ships.range_text(ships.warp_range(no_drive, tables)) == "no hyperdrive"
    assert ships.primary_range([bang, explorer], tables)["ship"] == "Bang"


class Texts:
    def name(self, item_id):
        return {"HYPERDRIVE": "Hyperdrive", "UP_HYP4": "S-Class Hyperdrive Upgrade"}.get(item_id)

    def item(self, item_id, text=None):
        return {"text": item_id, "icon": "x.png"}


def test_the_ships_table_explains_the_estimate_and_lists_the_primary_ships_technology():
    """The range cell's tooltip lists what adds up to it; damaged slots are counted, not listed as technology;
    the primary ship's technology says what each part adds."""
    out = ships.ship_sections(ships.ships_from_save(save()), dict(ships.FALLBACK), Texts())
    table = out[0]
    assert table["rows"][0][0] == "Bang (primary)" and table["rows"][1][0] == "(unnamed Explorer)"
    assert "S-Class Hyperdrive Upgrade: 220-265 ly" in table["rows"][0][3]["hint"]
    assert table["rows"][1][-1] == "15 / 0 / 16 (2 damaged)"
    tech = {r[0]["text"]: r[1:] for r in out[1]["rows"]}
    assert tech["HYPERDRIVE"] == ["96 / 120", "100 ly warp range"] and tech["UP_HYP4#66014"][1] == "220-265 ly warp range"
    assert tech["HDRIVEBOOST1"][1] == "opens red star systems" and tech["UP_HYP4#66014"][0] is None
    assert ships.ship_sections([], dict(ships.FALLBACK), Texts())[0]["text"] == "No ships in this save."
