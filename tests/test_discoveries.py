"""The save's discovery store (nms_connector/discoveries.py), with records shaped like the real save's.

Shapes taken from the real save on 2026-10-10 (1,409 records): `DD` {UA, DT, VP}, `DM` {CN}, `OWS`
{UID, USN, TS}, `FL` flags. The player's own id is the one every Sector record carries.
"""
from nms_connector import discoveries

ME, OTHER = "76561197971751554", "2533274919747064"
SYSTEM_A = 0x00A1_0002_925E80          # system 0xA1, planet nibble 0
PLANET_1 = SYSTEM_A | (1 << 52)
PLANET_2 = SYSTEM_A | (2 << 52)
SYSTEM_B = 0x00B2_0002_925E80


def rec(kind, address, uid=ME, name=None, stamp=1_700_000_000, flags=None, vp=None, user="ReatKay"):
    """A record as the save stores it."""
    out = {"DD": {"UA": hex(address), "DT": kind, "VP": vp if vp is not None else [1]},
           "DM": {"CN": name} if name else {},
           "OWS": {"LID": "", "UID": uid, "USN": user, "PTK": "ST", "TS": stamp}}
    if flags:
        out["FL"] = flags
    return out


def store():
    """A small store: two systems, a few scans, a named planet, a pet's animal, and a foreign record."""
    return [
        rec("Sector", SYSTEM_A, stamp=1_690_000_000),
        rec("SpacePoi", SYSTEM_B, stamp=1_690_000_100),
        rec("SolarSystem", SYSTEM_A, name="Aldrin Reach", stamp=1_700_000_100),
        rec("Planet", PLANET_1, name="Dusty Cactium", stamp=1_700_000_200),
        rec("Planet", PLANET_2, stamp=1_700_000_300),
        rec("Flora", PLANET_1, stamp=1_700_000_400, flags={"C": 1}),
        rec("Mineral", PLANET_1, stamp=1_700_000_500),
        rec("Animal", PLANET_1, stamp=1_700_000_600, vp=["0x320E447D6296A867", "0x1", "0x269DB40F01A2201D", "0xAA78C244162F491A"]),
        rec("Animal", PLANET_2, uid=OTHER, user="Charlie Papa", flags={"C": 1, "U": 1},
            vp=["0x320E447D6296A867", "0x1", "0x269DB40F01A2201D", "0xAA78C244162F491A"], stamp=1_600_000_000),
        rec("Flora", SYSTEM_B | (1 << 52), uid=OTHER, user="Charlie Papa", flags={"U": 1}),
    ]


def test_the_players_own_id_is_the_one_on_sector_records():
    """own_uid takes the most common UID among Sector and SpacePoi records, which are always the player's
    own, so records of other players that are more numerous overall do not become 'mine'. Getting this wrong
    would claim hundreds of other players' scans as the user's discoveries."""
    records = store() + [rec("Flora", PLANET_1, uid=OTHER) for _ in range(20)]
    assert discoveries.own_uid(records) == ME
    assert discoveries.own_uid([rec("Flora", PLANET_1, uid=OTHER)]) == OTHER, "no sector records: the overall majority"
    assert discoveries.own_uid([]) is None


def test_parse_makes_compact_rows_and_marks_whose_they_are():
    """parse() yields JSON-safe rows with kind, packed address, name, discoverer, ownership, time, raw flags
    and - for animals only - the validation seeds, and skips records without a kind or an address. The
    snapshot keeps these rows, so they must survive a round trip through JSON."""
    import json
    rows = discoveries.parse(store() + [{"DD": {"DT": "Flora"}}, "not a record", {"DD": {"UA": "0x1"}}])
    assert len(rows) == 10
    by = {(r["k"], r["a"]): r for r in rows}
    assert by[("SolarSystem", SYSTEM_A)]["n"] == "Aldrin Reach" and by[("SolarSystem", SYSTEM_A)]["m"] is True
    foreign = by[("Animal", PLANET_2)]
    assert foreign["m"] is False and foreign["o"] == "Charlie Papa" and foreign["f"] == ["C", "U"]
    seeds = by[("Animal", PLANET_1)]["s"]
    assert seeds[0] == 0x320E447D6296A867 and seeds[2] == 0x269DB40F01A2201D and seeds[3] == 0xAA78C244162F491A
    assert seeds[1] is None, "an unusable entry keeps its place, so the species seed stays at index 2"
    assert by[("Flora", PLANET_1)]["s"] == [], "only animals carry seeds"
    assert json.loads(json.dumps(rows)) == rows


def test_small_numbers_in_vp_are_not_seeds():
    """A sector record's VP holds the plain number 512, not a seed; only values above 16 bits count as seeds,
    so an unrelated integer never joins a pet to an animal record."""
    assert discoveries._seed("0x55A739271D8520AC") == 0x55A739271D8520AC
    assert discoveries._seed(512) is None and discoveries._seed(True) is None and discoveries._seed("nope") is None


def test_flags_are_kept_raw_and_never_interpreted():
    """FL.U appeared on 190 records, all of them other players'; FL.C and FL.F are unexplained. The reader
    only reports which flag keys are set, in sorted order, and treats a false flag as unset - no meaning is
    attached, because none could be proven."""
    row = discoveries.parse([rec("Sector", SYSTEM_A), rec("Flora", PLANET_1, flags={"U": 1, "C": 1, "F": 0})])[1]
    assert row["f"] == ["C", "U"]


def test_the_book_counts_names_and_groups_by_system():
    """The book answers the page's questions: counts per kind (own and all), the named records newest first,
    and a per-system tally of the player's own scans, most scanned first. Ties break on the address so the
    order never depends on the order in the save."""
    book = discoveries.DiscoveryBook(discoveries.parse(store()))
    assert book.counts(book.mine) == {"SolarSystem": 1, "Planet": 2, "Animal": 1, "Flora": 1, "Mineral": 1,
                                      "SpacePoi": 1, "Sector": 1}
    assert book.counts()["Animal"] == 2
    assert [r["n"] for r in book.named()] == ["Dusty Cactium", "Aldrin Reach"]
    systems = book.by_system()
    assert [e["system"] for e in systems][0] == SYSTEM_A
    first = systems[0]
    assert (first["planets"], first["plants"], first["creatures"], first["minerals"], first["scanned"], first["named"]) \
        == (2, 1, 1, 1, 3, 2)
    assert all(e["system"] != (SYSTEM_B | (1 << 52)) for e in systems), "keys have no planet nibble"
    assert [e["system"] for e in book.by_system(mine_only=False)].count(SYSTEM_B) == 1


def test_animals_join_by_creature_seed_and_the_players_own_record_wins():
    """animal_by_seed maps a pet's CreatureSeed (VP index 0) to its animal record; when two records share
    the seed the player's own is preferred, so 'where did I first scan this' is answered with their scan."""
    book = discoveries.DiscoveryBook(discoveries.parse(store()))
    found = book.animal_by_seed()[0x320E447D6296A867]
    assert found["m"] is True and found["a"] == PLANET_1


def test_matches_filters_by_kind_and_by_name_terms():
    """matches() finds named records by every term (case-folded) and restricts to the asked kinds; the
    player's own come first. The persona uses it for 'did I name a planet ...'."""
    book = discoveries.DiscoveryBook(discoveries.parse(store()))
    assert [r["n"] for r in discoveries.matches(book, ["dusty"], {"Planet"})] == ["Dusty Cactium"]
    assert discoveries.matches(book, ["dusty"], {"Animal"}) == []
    assert discoveries.matches(book, [], {"Animal"}) == [], "unnamed records have nothing to show, so they never match"
    assert discoveries.matches(book, ["zzz"], set()) == []


def test_a_huge_or_empty_store_is_bounded_and_safe():
    """An empty or missing store gives an empty, falsy book, and a store beyond MAX_RECORDS is cut. A damaged
    save must not be able to grow the snapshot without limit."""
    assert not discoveries.DiscoveryBook(None) and discoveries.parse(None) == []
    many = [rec("Flora", PLANET_1, stamp=i + 1) for i in range(discoveries.MAX_RECORDS + 50)]
    assert len(discoveries.parse(many)) == discoveries.MAX_RECORDS


def test_matches_looks_only_at_named_rows_so_unnamed_ones_cannot_crowd_them_out():
    """The real save has 73 own planets of which 20 carry a name, and the 12 best by date were all unnamed: taking
    the best rows before dropping the unnamed ones made 'which planets did I name?' list no planet at all. Only
    named rows are candidates, so the limit applies to rows that can be shown."""
    rows = [rec("Planet", SYSTEM_A | ((i % 15 + 1) << 52), stamp=1_800_000_000 + i) for i in range(40)]
    rows.append(rec("Planet", PLANET_1, name="Old Named", stamp=1_000_000_000))
    book = discoveries.DiscoveryBook(discoveries.parse([rec("Sector", SYSTEM_A)] + rows))
    found = discoveries.matches(book, [], {"Planet"}, limit=3)
    assert [r["n"] for r in found] == ["Old Named"]
