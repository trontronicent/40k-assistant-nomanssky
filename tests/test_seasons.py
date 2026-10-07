"""Expeditions (the game's seasons): names and rewards from the language texts, researched dates, the save's season
state, and the persona's block (seasons.py, summary.season_of)."""

import json
from datetime import date

from nms_connector import seasons, summary
from nms_connector.seasons import SeasonBook

ENGLISH = {
    "UI_SEASON_22_NAME": "Swarm", "UI_SEASON_22_MAIN_TITLE": "Expedition 22: The Swarm",
    "UI_EXPED22_SUMMARY": "Fight the swarm.",
    "UI_SEASON_23_NAME": "Our Journey Continues", "UI_SEASON_23_MAIN_TITLE": "Our Journey Continues",
    "UI_EXPED23_SUMMARY": "Time travel through iterations of an infinite universe.",
    "UI_EXPED23_DETAIL_DESC": "Complete <TECHNOLOGY>Milestones<> to earn new equipment.",
    "UI_EXPD_TITLE_23_NAME_L": "Title: 'Time Traveller'", "UI_BANNER_EXPD_23_NAME_L": "Our Journey Continues Banner",
    "BLD_DECAL_EXPD_23_NAME_L": "Our Journey Continues Decal", "UI_EXPD_EGG_23_NAME_L": "Diplo Egg",
    "UI_EXPD_GUN_23_NAME_L": "Starbound v0.27", "UI_EXPD_SHIP_23A_NAME_L": "Golden Rasamama S36",
    "BLD_EXPD_POSTER23A_NAME_L": "Framed Launch Art", "BLD_EXPD_POSTER23B_NAME_L": "Framed Next Art",
    "BLD_EXPD_BUGHEAD5_NAME_L": "Prized Exoskeleton",       # a base part, not a season reward: 5 is not a season here
}
LOCAL = {"UI_SEASON_23_NAME": "Unsere Reise geht weiter", "UI_EXPD_EGG_23_NAME_L": "Diplo-Ei"}


def _book():
    return SeasonBook.from_texts(ENGLISH, LOCAL, "german")


def test_the_book_reads_names_summaries_and_reward_kinds_from_the_language_texts():
    """Season 23 gets its name in both languages, the summary and how-it-works text (colour markup removed) and every
    reward with its kind; a key that only looks similar (BUGHEAD5) is not a reward of any season."""
    book = _book()
    assert sorted(book.seasons) == [22, 23] and book.latest == 23
    s = book.seasons[23]
    assert book.name(23) == "Our Journey Continues (Unsere Reise geht weiter)"
    assert s["detail"]["en"] == "Complete Milestones to earn new equipment."
    kinds = {r["en"]: r["kind"] for r in s["rewards"]}
    assert kinds == {"Title: 'Time Traveller'": "title", "Our Journey Continues Banner": "banner",
                     "Our Journey Continues Decal": "decal", "Diplo Egg": "egg", "Starbound v0.27": "multi-tool",
                     "Golden Rasamama S36": "starship", "Framed Launch Art": "poster", "Framed Next Art": "poster"}
    assert book.seasons[22]["rewards"] == []


def test_only_season_keys_are_asked_for_in_the_language_pass():
    """wanted_key accepts names, texts and reward names and nothing else, so the one pass over the language files
    keeps the stored texts small."""
    assert all(seasons.wanted_key(k) for k in ENGLISH if "BUGHEAD" not in k)
    assert not seasons.wanted_key("BLD_EXPD_BUGHEAD5_NAME_L")
    assert not seasons.wanted_key("UI_EXPED23_STAGE_TITLE_6") and not seasons.wanted_key("ITEM_COPPER")


def test_a_question_names_an_expedition_by_number_or_name_but_not_by_a_frigate_word():
    """"expedition 22" and "Swarm" name season 22; a question about the frigates' expeditions is not a season question
    (the frigates have expeditions too), and a short word that is only part of another is not a name."""
    book = _book()
    assert book.named_in("What did expedition 22 give?") == [22]
    assert book.named_in("tell me about the swarm") == [22]
    assert book.named_in("what about nests") == []
    assert seasons.asked_about({"which", "season", "is", "it"})
    assert not seasons.asked_about({"when", "do", "my", "frigates", "return", "from", "expedition"})


def test_timing_says_running_ended_first_run_or_unknown():
    """The researched file gives a running expedition with days gone and left (an estimate when Hello Games named no
    end), an ended one, a first run of an old one - and nothing for one that was not researched."""
    research = {"seasons": {"23": {"start": "2026-09-17", "weeks": 6, "official_end": None},
                            "5": {"first_run": ["2022-02-24", "2022-04-04"]}}}
    text, running = seasons.timing(23, research, date(2026, 10, 7))
    assert running and "started 2026-09-17 (20 days ago)" in text and "2026-10-29 (22 days left)" in text and "estimate" in text
    assert seasons.timing(23, research, date(2026, 12, 1)) == ("ran from 2026-09-17 to about 2026-10-29", False)
    assert seasons.timing(23, research, date(2026, 9, 1)) == ("starts 2026-09-17", False)
    assert seasons.timing(5, research, date(2026, 10, 7))[0].startswith("first ran 2022-02-24 to 2022-04-04")
    assert seasons.timing(22, research, date(2026, 10, 7)) == (None, False)
    assert seasons.timing(23, {"seasons": {"23": {"start": "garbage"}}}, date(2026, 10, 7)) == (None, False)


def test_the_expedition_block_for_a_current_season_question():
    """"Which season is it?" gives the newest expedition with dates, what it is, the rewards the game names (names in
    both languages), that the save is a normal game, and the list of all expeditions."""
    research = {"seasons": {"23": {"start": "2026-09-17", "weeks": 6}}, "facts": ["Expeditions last about six weeks."]}
    text = "\n".join(seasons.expedition_lines(_book(), research, "Which season is it?", date(2026, 10, 7),
                                              {"active": False, "number": None, "redeemed": 0}))
    assert "newest is Expedition 23 \"Our Journey Continues (Unsere Reise geht weiter)\"" in text
    assert "this is the current expedition" in text and "Your save is a normal game" in text
    assert "egg: Diplo Egg (Diplo-Ei)" in text and "2 posters" in text
    assert "All expeditions (first-run dates where researched): 22 Swarm, 23 Our Journey Continues" in text and "about six weeks" in text


def test_the_block_names_a_past_expedition_and_an_expedition_save():
    """A question naming expedition 22 gets that one (and says its dates are unknown when not researched); a save that
    is an expedition says which, with the number of redeemed rewards."""
    text = "\n".join(seasons.expedition_lines(_book(), {}, "What was the Swarm expedition?", date(2026, 10, 7),
                                              {"active": True, "number": 22, "redeemed": 3}))
    assert "Expedition 22 \"Swarm\" - when it ran is not in the game files" in text
    assert "Your save is expedition 22" in text and "redeemed: 3" in text
    assert seasons.expedition_lines(_book(), {}, "How much copper do I have?", date(2026, 10, 7), None) == []
    assert seasons.expedition_lines(SeasonBook(), {}, "which season?", date(2026, 10, 7), None) == []


def test_the_save_says_whether_it_is_an_expedition():
    """SeasonId 0 is a normal game even though SeasonNumber holds a default 1 (checked on a real save, 2026-10-07);
    a SeasonId puts the number and counts the redeemed rewards."""
    normal = summary.season_of({"SeasonData": {"SeasonId": 0, "SeasonNumber": 1}}, {"RedeemedSeasonRewards": []})
    assert normal == {"active": False, "number": None, "redeemed": 0}
    active = summary.season_of({"SeasonData": {"SeasonId": 7, "SeasonNumber": 23}, "EarnedSeasonSpecialRewards": ["A"]},
                               {"RedeemedSeasonRewards": ["X", "Y"]})
    assert active == {"active": True, "number": 23, "redeemed": 3}
    assert summary.season_of({}, {}) == {"active": False, "number": None, "redeemed": 0}


def test_the_researched_files_are_valid_and_carry_their_sources():
    """research/expeditions.json and cooking.json parse, name their sources, and every date in them is a real date:
    a researched fact without a source, or a typo in a date, would silently mislead the persona."""
    for loader, name in ((seasons.load_research, "expeditions"), (None, "cooking")):
        data = loader() if loader else json.loads((seasons.RESEARCH_FILE.parent / "cooking.json").read_text(encoding="utf-8"))
        assert data["researched"] and data["sources"] and all(s.startswith("https://") for s in data["sources"])
        assert data["facts"]
    for number, info in seasons.load_research()["seasons"].items():
        assert number.isdigit()
        for d in info.get("first_run", []) + [info.get("start"), info.get("official_end")]:
            assert d is None or date.fromisoformat(d)
    assert seasons.load_research(seasons.RESEARCH_FILE.with_name("missing.json")) == {}


def test_a_reward_name_finds_its_expedition_only_in_a_reward_or_season_question():
    """"Which expedition gave the Starbound multi-tool?" opens expedition 23 by the reward's distinctive words; the
    same words in an unrelated question ("Diplo egg" on a planet) must not open any expedition, and a poster named
    only by filler words never matches."""
    book = _book()
    research = {"seasons": {"23": {"start": "2026-09-17", "weeks": 6}}}
    ask = lambda q: "\n".join(seasons.expedition_lines(book, research, q, date(2026, 10, 7), None))
    assert "Expedition 23" in ask("Which expedition gave the Starbound v0.27 multi-tool?")
    assert "Expedition 23" in ask("Which expedition gave the Diplo Egg?")
    assert ask("Where can I find a diplo egg on a planet?") == ""
    assert seasons.rewards_named_in(book, "the framed art poster") == []


def test_the_expedition_list_shows_researched_first_run_dates():
    """The list of all expeditions carries the researched dates, so "list all expeditions with their dates" can be
    answered for the ones that were researched and says nothing for the rest."""
    research = {"seasons": {"22": {"first_run": ["2026-05-27", "2026-07-19"]}}}
    text = "\n".join(seasons.expedition_lines(_book(), research, "list all expeditions", date(2026, 10, 7), None))
    assert "22 Swarm (2026-05-27 to 2026-07-19), 23 Our Journey Continues" in text
