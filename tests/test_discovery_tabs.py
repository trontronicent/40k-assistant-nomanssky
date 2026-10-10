"""The Discoveries and Companions tabs, from a save shaped like the real one (plugin 0.15.0).

`summarize` is the real one; the views are called with a stand-in context that names two systems. Pets and
records copy the real save (2026-10-10): 11 pets / 4 eggs / 11 of 30 slots there, a pet's creature seed equal to
an animal record's `VP[0]`.
"""
import json

from nms_connector import companions_view, discoveries, discoveries_view, pets
from nms_connector.discoveries import DiscoveryBook
from nms_connector.summary import summarize
from test_connector import readable_save
from test_discoveries import PLANET_1, PLANET_2, SYSTEM_A, SYSTEM_B, rec
from test_pets import move_table, raw_pet

NOW = 1_791_600_000.0
NAMES = {SYSTEM_A: "Aldrin Reach"}


class Ctx:
    """The one thing the views ask of the planets context: a system's visit record."""

    @staticmethod
    def visit(key):
        return {"name": NAMES[key]} if key in NAMES else None


def snapshot():
    """A real summary of a save with pets, eggs, slots and discovery records."""
    save = readable_save()
    state = save["BaseContext"]["PlayerStateData"]
    state["Pets"] = [raw_pet(), raw_pet(CustomName="", CreatureID="^PROTOROLLER", UA="0x20B70002925E80",
                                        CreatureSeed=[True, "0x1111111111111111"], PetBattlerVictories=0)]
    state["Eggs"] = [raw_pet(CustomName="", CreatureID="^FIEND", Trust=0.7)]
    state["UnlockedPetSlots"] = [True] * 10 + [False] * 20
    save["DiscoveryManagerData"] = {"DiscoveryData-v1": {"Store": {"Record": [
        rec("Sector", SYSTEM_A), rec("SpacePoi", SYSTEM_B),
        rec("SolarSystem", SYSTEM_A, name="Aldrin Reach"), rec("Planet", PLANET_1, name="Dusty Cactium"),
        rec("Flora", PLANET_1), rec("Mineral", PLANET_1), rec("Mineral", PLANET_2),
        rec("Animal", PLANET_1, stamp=1_700_000_600,
            vp=["0x320E447D6296A867", "0x109BB757445D45AE", "0x269DB40F01A2201D", "0xAA78C244162F491A"]),
        rec("Animal", PLANET_2, uid="999", user="Charlie Papa", flags={"U": 1}),
    ]}}}
    return summarize(save)


def book():
    """A PetBook with harvest words and the move table."""
    texts = {"UI_LABEL_HARVEST_COW": "Collect Milk", "FOOD_COW_VEG_NAME_L": "Fresh Milk",
             "FOOD_COW_MEAT_NAME_L": "Raw Steak"}
    out = pets.PetBook.from_texts(texts, None, None)
    out.moves = pets.parse_moves(move_table())
    return out


def test_the_snapshot_carries_the_companions_and_the_discoveries():
    """summarize() adds `companions` (pets, eggs, the unlocked/total slots) and `discoveries` (compact rows) and
    keeps the old `pets` count. Both are JSON-safe, because the page and the persona read them as plain data."""
    snap = snapshot()
    assert snap["pets"] == 2
    assert [p["id"] for p in snap["companions"]["pets"]] == ["COW", "PROTOROLLER"]
    assert [e["id"] for e in snap["companions"]["eggs"]] == ["FIEND"] and snap["companions"]["slots"] == [10, 30]
    assert len(snap["discoveries"]) == 9
    assert json.loads(json.dumps(snap["companions"])) == snap["companions"]
    assert json.loads(json.dumps(snap["discoveries"])) == snap["discoveries"]


def test_a_save_without_either_still_summarises():
    """The bare test save has no pets and no discovery store: the keys are present and empty, never an error.
    Older saves and fresh games must keep working."""
    snap = summarize(readable_save())
    assert snap["companions"] == {"pets": [], "eggs": [], "slots": [0, 0]} and snap["discoveries"] == []


def test_the_discoveries_tab_lists_counts_systems_and_names():
    """The tab opens with a note, then the counts split into yours and other players', the scans per system
    (clickable, keyed by the system's hex key) and the named records with their place. A system you only
    appear in through a sector record is not listed as a scan site."""
    snap = snapshot()
    out = discoveries_view.sections(snap, Ctx(), DiscoveryBook(snap["discoveries"]))
    assert out[0]["type"] == "text" and "no completion percentage" in out[0]["text"]
    stats = next(s for s in out if s.get("title") == "Your discoveries")
    values = {i["label"]: i["value"] for i in stats["items"]}
    assert values["Creatures"] == "1" and values["Plants"] == "1" and values["Minerals"] == "2"
    assert values["Other players' records"] == "1" and values["Named by someone"] == "2"
    table = next(s for s in out if s.get("id") == "discoveries-by-system")
    assert table["columns"][:2] == ["System", "Plants"] and table["row_action"] == "open_system"
    assert table["rows"][0][0] == "Aldrin Reach" and table["row_keys"][0] == f"{SYSTEM_A:x}"
    assert table["rows"][0][1:5] == [1, 1, 2, 1] or table["rows"][0][1:5] == [1, 1, 2, 2]
    named = next(s for s in out if s.get("id") == "discoveries-named")
    assert {row[0] for row in named["rows"]} == {"Aldrin Reach", "Dusty Cactium"}
    dusty = next(row for row in named["rows"] if row[0] == "Dusty Cactium")
    assert dusty[1] == "Planet" and dusty[2] == "Aldrin Reach, planet 1" and dusty[4] == "you"


def test_an_empty_store_and_no_save_say_so():
    """No save yet, or a save with no records, gives one explanatory line instead of empty tables."""
    assert "No save has been read" in discoveries_view.sections(None, Ctx(), DiscoveryBook(None))[0]["text"]
    assert "no discovery records" in discoveries_view.sections({"units": 1}, Ctx(), DiscoveryBook(None))[0]["text"]


def test_tables_stay_within_the_apps_row_limit():
    """A save with thousands of scanned systems and names yields at most MAX_SYSTEM_ROWS / MAX_NAMED_ROWS rows
    (the app caps a table at 500 rows and would drop the rest silently)."""
    many = [rec("Flora", (0x00A1_0002_925E80 & ~(0xFFF << 40)) | (i << 40) | (1 << 52), name=f"P{i}", stamp=1_700_000_000 + i)
            for i in range(1, 900)]
    snap = {"discoveries": discoveries.parse(many)}
    out = discoveries_view.sections(snap, Ctx(), DiscoveryBook(snap["discoveries"]))
    by_system = next(s for s in out if s.get("id") == "discoveries-by-system")
    named = next(s for s in out if s.get("id") == "discoveries-named")
    assert len(by_system["rows"]) == discoveries_view.MAX_SYSTEM_ROWS
    assert len(named["rows"]) == discoveries_view.MAX_NAMED_ROWS
    assert len(by_system["rows"]) == len(by_system["row_keys"])


def test_the_companions_tab_shows_roster_abilities_harvest_and_first_scan():
    """One row per pet: name (seeds and stat classes in the tooltip), creature, type, biome, trust, age, wins,
    the abilities with the game's description in the tooltip, the harvest read from the game's text, the raw
    traits, where its kind was first scanned (the seed join) and its origin system."""
    snap = snapshot()
    out = companions_view.sections(snap, Ctx(), book(), DiscoveryBook(snap["discoveries"]), NOW)
    assert out[0]["type"] == "text" and "not stored in a readable form" in out[0]["text"]
    stats = next(s for s in out if s.get("title") == "Companions")
    values = {i["label"]: i["value"] for i in stats["items"]}
    assert values["Companions"] == "2 of 10 unlocked slots" and values["Eggs"] == "1" and values["Arena wins (all)"] == "22"
    roster = next(s for s in out if s.get("id") == "companions-roster")
    cow = dict(zip(roster["columns"], roster["rows"][0], strict=True))
    assert cow["Name"]["text"] == "Unzy Bunzy Bowa" and "Creature seed: 0x320E447D6296A867" in cow["Name"]["hint"]
    assert (cow["Creature"], cow["Type"]["text"], cow["Biome"]) == ("Cow", "Prey", "Lush")
    assert cow["Type"]["hint"].startswith("Prey:") and "Not confirmed" in cow["Personality (3 raw values)"]["hint"]
    assert cow["Trust"] == {"text": "75 %", "sort": 0.75} and cow["Arena wins"]["sort"] == 22
    assert cow["Abilities"]["text"] == "4" and "ATTACK_DUST (ATTACK): Direct damage of one affinity" in cow["Abilities"]["hint"]
    assert cow["Harvest"] == "Collect Milk -> Fresh Milk / Raw Steak"
    assert cow["Personality (3 raw values)"]["text"] == "+0.25 / -0.73 / -0.16"
    assert cow["First scanned"].endswith("Aldrin Reach, planet 1"), cow["First scanned"]
    assert cow["Origin"] != "–"
    roller = dict(zip(roster["columns"], roster["rows"][1], strict=True))
    assert roller["Name"]["text"] == "Protoroller (unnamed)" and roller["Harvest"] == "–"
    assert roller["First scanned"] == "–", "its creature seed matches no animal record"


def test_eggs_are_listed_and_the_move_table_error_is_shown_not_hidden():
    """The eggs get their own table; when the move table or the texts could not be read the tab says so in a
    notice instead of showing blank abilities as if there were none."""
    snap = snapshot()
    broken = pets.PetBook(error="RuntimeError: table moved")
    out = companions_view.sections(snap, Ctx(), broken, DiscoveryBook(snap["discoveries"]), NOW)
    eggs = next(s for s in out if s.get("id") == "companions-eggs")
    assert [row[0] for row in eggs["rows"]] == ["Fiend"] and eggs["rows"][0][3]["text"] == "70 %"
    note = next(s for s in out if s["type"] == "notice")
    assert "table moved" in note["text"]


def test_no_companions_say_so_and_no_save_says_so():
    """A save with neither pets nor eggs, and no save at all, each give one explanatory line."""
    assert "no companions" in companions_view.sections({"companions": {"pets": [], "eggs": [], "slots": [0, 0]}},
                                                       Ctx(), pets.PetBook(), DiscoveryBook(None), NOW)[0]["text"]
    assert "No save has been read" in companions_view.sections(None, Ctx(), pets.PetBook(), DiscoveryBook(None), NOW)[0]["text"]
