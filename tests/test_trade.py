"""Tests for economies and trade: the trading table, star records in memory, routes and the Trade tab."""

import struct

from nms_connector import memory, planets_view, trade
from nms_connector.gamedata import GameData
from nms_connector.game_install import GameInstall
from nms_connector.history import PlanetHistory
from nms_connector.live import LiveMemory
from test_gamedata import build_pak, make_game
from test_memory import FakeReader, planet_blob

SYSTEM_98 = 0x620002925E80
SYSTEM_115 = 0x730002925E80
FAR = (100 & 0xFFF) | (100 & 0xFFF) << 12 | 2 << 24 | 7 << 40      # another region of Euclid


def trading_table(rows=None) -> bytes:
    """A tradingclassdatatable.mbin in the game's layout: header, CategoryData, 7 GcTradingClassData."""
    rows = rows or [(6, 0), (3, 1), (5, 2), (0, 3), (2, 4), (4, 5), (1, 6)]       # (needs, sells) as in the game
    data = bytearray(0x20 + 0x4F0)
    data[:8] = b"\xcc" * 8
    for i, (needs, sells) in enumerate(rows):
        at = 0x20 + 0x360 + i * 0x38
        struct.pack_into("<6f", data, at + 0x18, 1.8, 2.0, 0.9, 1.4, 1.6, 0.7)
        struct.pack_into("<2i", data, at + 0x30, needs, sells)
    return bytes(data)


def test_trading_table_is_read_from_the_game_layout():
    """Each economy's category to buy cheaply and to sell well, with price factors, comes from the game's table;
    a table whose values make no sense (same category both ways) is refused, so the built-in copy is used."""
    table = trade.parse_trading_table(trading_table())
    assert table["Mining"] == {"needs": "Energy", "sells": "Mineral", "buys_at": (1.4, 1.8), "sells_at": (0.7, 0.9)}
    assert table == trade.FALLBACK
    assert trade.parse_trading_table(trading_table([(1, 1)] * 7)) is None
    assert trade.parse_trading_table(b"short") is None
    assert trade.goods("Mineral") == [f"TRA_MINERALS{i}" for i in range(1, 6)] and trade.goods("None") == []


def star_record(trading=2, wealth=1, conflict=1, planets=3, race=1, star=0, seeds=()) -> bytearray:
    """A GcGalaxyStarAttributesData record with the given economy and planet seeds."""
    b = bytearray(memory.STAR_SIZE)
    for index, seed in seeds:
        struct.pack_into("<Q?", b, memory.STAR_PLANET_SEEDS + index * 0x10, seed, True)
    struct.pack_into("<2i", b, memory.STAR_TRADING, trading, wealth)
    struct.pack_into("<7i", b, memory.STAR_TAIL, 0, conflict, planets, 0, 0, race, star)
    return b


def test_star_records_are_found_through_planet_seeds():
    """A system's economy is read from the galaxy map's star record that holds every known planet's seed at
    that planet's index; a record holding only one of them (another system) is not taken."""
    p0 = memory.parse_planet(bytes(planet_blob("A", 0, seed=0x1111)))
    p2 = memory.parse_planet(bytes(planet_blob("C", 2, seed=0x3333)))
    region = bytearray(0x8000)
    decoy = star_record(trading=0, seeds=[(0, 0x1111), (2, 0x9999)])            # seed of A, but not of C
    region[0x100:0x100 + len(decoy)] = decoy
    real = star_record(trading=2, wealth=2, conflict=2, race=2, seeds=[(0, 0x1111), (2, 0x3333)])
    region[0x1000:0x1000 + len(real)] = real
    found = memory.find_star_attributes(FakeReader({0x100000: region}), {SYSTEM_98: [p0, p2]})
    assert found[SYSTEM_98]["economy"] == "Trading" and found[SYSTEM_98]["wealth"] == "Wealthy"
    assert found[SYSTEM_98]["conflict"] == "High" and found[SYSTEM_98]["race"] == "Korvax"
    assert memory.parse_star_attributes(bytes(star_record(trading=9))) is None


def test_star_search_starts_in_the_preferred_region_and_stops_when_done():
    """The regions holding the name cache are searched first and the pass stops once every system is found:
    the regions after it are never read, which is what keeps the economy pass short on 5 GB of memory."""
    p0 = memory.parse_planet(bytes(planet_blob("A", 0, seed=0x1111)))
    star = bytearray(0x2000)
    star[0x800:0x800 + memory.STAR_SIZE] = star_record(seeds=[(0, 0x1111)])
    regions = {0x100000: bytearray(0x2000), 0x200000: star, 0x300000: bytearray(0x2000)}

    class CountingReader(FakeReader):
        read_bases: list[int] = []

        def read(self, address, size):
            self.read_bases.append(address & ~0xFFFFF)
            return super().read(address, size)

    reader = CountingReader(regions)
    found = memory.find_star_attributes(reader, {SYSTEM_98: [p0]}, prefer=[0x200000])
    assert found[SYSTEM_98]["economy"] == "Trading"
    assert set(reader.read_bases) == {0x200000}
    assert memory.find_star_attributes(FakeReader(regions), {SYSTEM_98: [p0]})[SYSTEM_98]["economy"] == "Trading"


def test_economies_are_stored_and_read_once_per_system(tmp_path):
    """Economies persist in the planet history; the live reader looks for a system's star record only while
    it has no economy recorded, so the extra memory pass runs once per new system."""
    history = PlanetHistory(tmp_path / "h.json")
    assert history.record_economies({SYSTEM_98: {"economy": "Mining", "wealth": "Poor"}}, "t1") == 1
    assert history.record_economies({SYSTEM_98: {"economy": "Mining", "wealth": "Poor"}}, "t2") == 0
    history.save()
    assert PlanetHistory(tmp_path / "h.json").economies[SYSTEM_98]["economy"] == "Mining"

    region = bytearray(0x10000)
    region[0x1000:0x1000 + memory.PLANET_SIZE] = planet_blob("B", 0, system=SYSTEM_115, seed=0x42)
    reader = FakeReader({0x100000: region})
    calls = []

    def finder(r, systems, prefer=()):
        calls.append(sorted(systems))
        return {k: {"economy": "Scientific", "wealth": "Average", "conflict": "Low", "race": "Gek"} for k in systems}

    live = LiveMemory(PlanetHistory(tmp_path / "h2.json"), opener=lambda p: reader, pid_finder=lambda: 4242,
                      scanner=lambda r, s, a: memory.scan(r, s, a), star_finder=finder)
    live.tick(None, None, 0)
    live.tick(None, None, 400)                       # rescan, economy already known
    assert calls == [[SYSTEM_115]] and live.history.economies[SYSTEM_115]["economy"] == "Scientific"


def test_routes_pick_the_nearest_buyer_and_seller():
    """For each kind of goods the nearest system selling it cheaply and the nearest needing it are named;
    a missing half stays None so the page can say which economy to look for."""
    economies = {SYSTEM_98: {"economy": "Mining"}, SYSTEM_115: {"economy": "Manufacturing"}, FAR: {"economy": "Mining"}}
    routes = {r["category"]: r for r in trade.routes(economies, trade.FALLBACK, SYSTEM_115)}
    minerals = routes["Mineral"]                    # Mining sells minerals, Manufacturing needs them
    assert minerals["buy"] == SYSTEM_98 and minerals["sell"] == SYSTEM_115 and minerals["between"] == 0
    assert routes["Component"]["buy"] == SYSTEM_115 and routes["Component"]["sell"] is None
    assert routes["Tech"]["buy"] is None and routes["Tech"]["sell"] is None


class FakeTexts:
    def lookup(self, item_id):
        return {"en": item_id, "local": item_id}

    def icon_name(self, item_id):
        return None

    def text(self, key):
        return {"UI_ECON_CLASS_MINING_1": {"en": "Mining", "local": "Bergbau"}}.get(key)


class Live:
    status, error, current, current_source = "ok", None, None, "planets"
    current_system = SYSTEM_115


def test_trade_tab_lists_economies_and_routes(tmp_path):
    """The Trade tab shows each recorded economy (your system first) with what is cheap and what sells well
    there, the routes between your systems, and the economy to look for where none is known; the system map's
    star and the visited-systems table carry the economy too."""
    history = PlanetHistory(tmp_path / "h.json")
    history.record_economies({SYSTEM_98: {"economy": "Mining", "wealth": "Poor", "conflict": "Low", "race": "Gek"},
                              SYSTEM_115: {"economy": "Manufacturing", "wealth": "Wealthy", "conflict": "High", "race": "Korvax"}}, "t")
    ctx = planets_view.Context(Live(), history, {}, FakeTexts(), None)
    economies, routes, note = planets_view.trade_sections(ctx)
    assert economies["rows"][0][1] == "Manufacturing" and economies["rows"][0][7] == "this system"
    assert economies["rows"][1][1] == "Mining (Bergbau)" and economies["rows"][1][5:7] == ["Minerals", "Energy"]
    minerals = next(r for r in routes["rows"] if r[0] == "Minerals")
    assert minerals[2].startswith("System ") and "(Mining (Bergbau))" in minerals[2] and "Manufacturing" in minerals[3]
    energy = next(r for r in routes["rows"] if r[0] == "Energy")
    assert energy[2].startswith("not found yet - look for: Power Generation")
    assert "x0.7-0.9" in note["text"] and "built-in" in note["text"]
    star = planets_view._star(SYSTEM_98, {}, [], ctx)
    items = {i["label"]: i["value"] for i in star["items"]}
    assert items["Economy"] == "Mining (Bergbau)" and items["Cheap to buy here (x0.7-0.9)"].startswith("Minerals: TRA_MINERALS1")
    visited = planets_view.visited_systems_sections(ctx, None)[-1]
    assert visited["columns"][-2:] == ["Economy", "Conflict"]


def test_a_cached_item_database_gets_the_trading_table(tmp_path):
    """An item cache written before the trading table existed is completed from the game files on load, without
    rebuilding the items; a fresh build reads it right away."""
    game = make_game(tmp_path / "game")
    precache = game.pcbanks / "NMSARC.Precache.pak"
    from test_gamedata import PRODUCTS, PRODUCT_LAYOUT, UPGRADES, UPGRADE_LAYOUT, build_table
    precache.write_bytes(build_pak({
        "metadata/reality/tables/nms_reality_gcproducttable.mbin": build_table(PRODUCTS, PRODUCT_LAYOUT, 0xC0),
        "metadata/reality/tables/nms_reality_gcproceduraltechnologytable.mbin": build_table(UPGRADES, UPGRADE_LAYOUT, 0x80),
        trade.TABLE_FILE: trading_table(),
    }))
    data = GameData(tmp_path / "data")
    data.load(game)
    assert data.trading_source == "game files" and data.trading["Fusion"]["sells"] == "Alloy"
    import json
    cache = json.loads(data.cache_file.read_text(encoding="utf-8"))
    del cache["trading"], cache["trading_source"]
    data.cache_file.write_text(json.dumps(cache), encoding="utf-8")
    again = GameData(tmp_path / "data")
    again.load(GameInstall(game.root, game.build_id, game.language, game.source))
    assert again.trading_source == "game files"
