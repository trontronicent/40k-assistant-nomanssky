"""Whose base is whose (reported 2026-10-21).

`PlayerStateData.PersistentPlayerBases` is not "your bases": it also holds every base the player downloaded
or visited, owned by another player. On the real save 134 of 171 entries were someone else's, and 67 of them
were stored twice, so the page showed strangers' bases as the player's own and counted several of them
twice. These tests pin the split and the two traps that made it wrong.
"""
from nms_connector import planets_view, summary
from nms_connector.history import PlanetHistory

ME = "76561197971751554"
SYSTEM = 4611351810039424


def save(bases, *, owners=(ME,)):
    """A save holding the given raw base entries, with `UsedDiscoveryOwnersV2` naming the player."""
    return {"BaseContext": {"PlayerStateData": {"UniverseAddress": {"GalacticAddress": {}},
                                                "PersistentPlayerBases": list(bases)}},
            "CommonStateData": {"UsedDiscoveryOwnersV2": [{"UID": uid} for uid in owners]}}


def base(name, uid, kind="HomePlanetBase", rid=None, updated=1757075039, usn=None):
    out = {"Name": name, "GalacticAddress": SYSTEM, "BaseType": {"PersistentBaseTypes": kind},
           "Objects": [], "LastUpdateTimestamp": updated, "Owner": {"UID": uid, "USN": usn or ""}}
    if rid:
        out["RID"] = rid
    return out


def test_only_the_players_own_bases_are_his():
    """A base is the player's when its owner id is his, whatever its type - the single thing that was wrong
    on the page, which called every downloaded base one of his."""
    snap = summary.summarize(save([
        base("Home", ME),
        base("Freighter", ME, kind="FreighterBase"),
        base("Ship", ME, kind="PlayerShipBase"),
        base("Station", ME, kind="PlayerSpaceStationBase"),
        base("Calypso Portal", "76561198030728485", kind="ExternalPlanetBase", usn="Pennyhero"),
    ]))
    mine = [b["name"] for b in snap["bases"] if b["mine"]]
    others = [b for b in snap["bases"] if not b["mine"]]
    assert mine == ["Home", "Freighter", "Ship", "Station"]
    assert [b["name"] for b in others] == ["Calypso Portal"]
    assert others[0]["owner"] == "Pennyhero", "the other player is named, so the base can be shown as theirs"
    assert snap["bases"][3]["type"] == "Space station base", "a station interior is a base type of its own"


def test_a_downloaded_base_stored_twice_is_counted_once():
    """The game saves a visited base again each time it fetches it: on the real save 67 bases appeared twice
    with the same RID and position and only a newer timestamp. Counting both inflated every bases line."""
    snap = summary.summarize(save([
        base("The Thirteenth", "76561198030728485", kind="ExternalPlanetBase", rid="oa3iJweWbk09",
             updated=1792556430),
        base("The Thirteenth", "76561198030728485", kind="ExternalPlanetBase", rid="oa3iJweWbk09",
             updated=1792560238),
    ]))
    assert len(snap["bases"]) == 1
    assert snap["bases"][0]["last_update"] == 1792560238, "the newer copy wins"


def test_bases_without_an_rid_are_all_kept():
    """Nothing identifies two RID-less entries as the same base, so dropping one would lose a real base -
    the dedup may only merge what the save itself says is one base."""
    snap = summary.summarize(save([base("Outpost", ME), base("Outpost", ME)]))
    assert len(snap["bases"]) == 2


def test_the_owner_is_read_from_the_save_not_guessed():
    """The player's id comes from `CommonStateData.UsedDiscoveryOwnersV2`. With no single owner there the
    type decides instead - guessing from "the owner most bases share" would call a visited portal hub the
    player's own on a save where he has few bases of his own."""
    assert summary.player_uid({"UsedDiscoveryOwnersV2": [{"UID": ME}]}) == ME
    assert summary.player_uid({"UsedDiscoveryOwnersV2": [{"UID": ME}, {"UID": "other"}]}) is None
    assert summary.player_uid({}) is None
    # Twenty strangers' bases and one of the player's: the fallback must still not follow the majority.
    many = [base(f"Theirs {i}", f"uid{i}", kind="ExternalPlanetBase", rid=f"r{i}") for i in range(20)]
    snap = summary.summarize(save([*many, base("Mine", ME)], owners=()))
    assert [b["name"] for b in snap["bases"] if b["mine"]] == ["Mine"]


def test_a_base_with_no_owner_is_not_treated_as_yours():
    """An entry the save gives no owner is not evidence that the player built it."""
    raw = base("Nameless", ME)
    raw["Owner"] = {}
    snap = summary.summarize(save([raw]))
    assert snap["bases"][0]["mine"] is False


class _Live:
    status, error, current, current_source = "ok", None, None, "planets"
    current_system = None


class _Texts:
    def lookup(self, item_id):
        return None

    def icon_name(self, item_id):
        return None

    def text(self, key):
        return None


def test_the_system_card_separates_your_bases_from_other_players(tmp_path):
    """The card lists them on two lines. Before this the other players' names appeared under
    "Your bases here" - the report that started this."""
    ctx = planets_view.Context(
        _Live(), PlanetHistory(tmp_path / "h.json"), {}, _Texts(), None,
        bases=[{"name": "Home", "mine": True, "system": SYSTEM},
               {"name": "Calypso Portal", "mine": False, "owner": "Pennyhero", "system": SYSTEM},
               {"name": "No owner", "mine": False, "owner": None, "system": SYSTEM}])
    assert ctx.bases_in(SYSTEM) == ["Home"]
    assert ctx.other_bases_in(SYSTEM) == ["Calypso Portal (Pennyhero)", "No owner"]
