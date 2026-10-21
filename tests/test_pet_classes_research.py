"""The pet battle tier research file and its write-up.

Nothing guarded `research/pet_classes.json` before: it is written by hand across many sessions and a
truncated write or a dropped section would have gone unnoticed until a persona answered from it.
These tests check the file parses, that the findings the write-up depends on are still present, and
that the two documents do not drift apart on the one number a reader will quote.
"""
import json
import re
from pathlib import Path

RESEARCH = Path(__file__).resolve().parent.parent / "research" / "pet_classes.json"
WRITEUP = RESEARCH.with_name("pet_tiers.md")


def _data():
    return json.loads(RESEARCH.read_text(encoding="utf-8"))


def test_the_file_opens_with_one_authoritative_answer():
    """CURRENT_ANSWER is the first key, so a reader does not have to date-sort eleven tier_source entries to
    find what is true now. It must carry the real table, the probabilities and the one open question."""
    d = _data()
    assert next(iter(d)) == "CURRENT_ANSWER", "the authoritative answer must come first in the file"
    a = d["CURRENT_ANSWER"]
    assert "30, 30, 25, 15" in a["the_table"]["CoreStatClassRollTable"]
    assert "1 in 296" in a["probabilities"] and "15%" in a["probabilities"]
    assert "PetBattlerSeed" in a["still_open"], "the remaining gap must be named"
    assert "33%" in a["never_do"], "the selection-bias warning must survive"


def test_falsified_claims_are_not_left_phrased_as_truth():
    """`conclusions` and `open` read as current fact, so a falsified entry there must carry its marker. The
    CreatureSeed claim and the 'compiled into the exe' claim were both believed and both wrong."""
    d = _data()
    creature = [c for c in d["conclusions"] if "CreatureSeed ALONE" in c]
    assert creature and all(c.startswith("FALSIFIED") for c in creature),         "the CreatureSeed conclusion must be marked falsified, not deleted and not left bare"
    where = d["tier_source"]["MECHANISM_NAMED_2026_10_20"]["where_the_table_lives"]
    assert where.startswith("WRONG"), "the compiled-into-the-exe claim must be marked wrong"
    assert "gcgametableglobals.mbin" in where, "and corrected to where the table really ships"


def test_the_research_file_parses_and_keeps_its_core_sections():
    """pet_classes.json is valid JSON and still carries the sections the write-up and the persona rely on:
    a hand-edited file losing `tier_source` or `observations` would quietly strip the whole finding."""
    d = _data()
    for key in ("researched", "codeword", "observations", "tier_source", "roll_table_weights",
                "overall_formula", "selection_bias", "hgpak_format"):
        assert key in d, f"research file lost its {key!r} section"
    assert d["codeword"], "the codeword is what the user names this work by"
    assert len(d["observations"]) == 21, "the 21 natural pet observations are the raw record"


def test_superseded_findings_are_retained_not_deleted():
    """The falsified `CreatureSeed` claim and the closed routes stay in the file, marked as superseded.
    Deleting a wrong conclusion loses the reason the next session must not retry it."""
    ts = _data()["tier_source"]
    assert "FALSIFIED_2026_10_20_by_save_oracle" in ts, "the falsification must stay on record"
    assert "measured_2026_10_20" in ts, "the superseded measurement must stay on record"
    for key in ("SOLVED_FIELDS_2026_10_20", "HASH_CONFIRMED_2026_10_20", "ROUTE2_NEGATIVE_2026_10_20",
                "MECHANISM_NAMED_2026_10_20"):
        assert key in ts, f"{key} records a closed route; losing it invites repeating the work"


def test_the_real_roll_table_is_recorded_with_its_correction():
    """The table read out of the game's own data, and the fact it corrects our estimate. The numbers are the
    whole point of the static analysis; the correction stops the superseded 8% being quoted again."""
    s = _data()["SOLVED_roll_table_2026_10_21"]
    assert "30, 30, 25, 15" in s["values"]["CoreStatClassRollTable"]
    assert "gcgametableglobals.mbin" in s["where"], "where it ships matters: it is data, not compiled in"
    assert "CORRECTS_OUR_MEASUREMENT" in s, "the correction to S must stay on record"
    assert "1 in 296" in s["practical"], "the triple-S rarity a reader will quote"


def test_the_tier_inputs_and_mechanism_are_recorded():
    """The two seeds and the named roll table are the whole finding, so they must be stated in the file
    itself rather than only in the write-up."""
    d = _data()
    solved = json.dumps(d["tier_source"]["SOLVED_FIELDS_2026_10_20"])
    assert "SpeciesSeed" in solved and "GenusSeed" in solved
    named = json.dumps(d["tier_source"]["MECHANISM_NAMED_2026_10_20"])
    for field in ("PetBattlerSeed", "CoreStatClassRollTable"):
        assert field in named, f"{field} is the mechanism's name as the game spells it"


def test_the_roll_table_shape_and_its_open_parameter():
    """The oracle's measured weights are kept as a record of what the method got right and wrong, now that
    static analysis has superseded them. Losing the superseded marker would let a reader quote S at 8%."""
    w = _data()["roll_table_weights"]
    assert "THE_SHAPE" in w, "the shape result is the headline finding"
    shape = json.dumps(w["THE_SHAPE"])
    assert "equal" in shape.lower() and "uniform" in shape.lower()
    assert w["caveats"], "the sample is small; the caveats are not optional"
    assert "SUPERSEDED" in w["THE_SHAPE"], "the shape estimate is superseded by the real table"
    assert "SUPERSEDED" in w["status"], "the measurement's status must say so"


def test_distributional_claims_are_marked_as_bias_free_only():
    """Frequencies must come from chosen-input batches, never from the tamed pets, which were hunted for
    the best. Without this note the 33% S rate reads as a natural rate and is wrong by about 4x."""
    d = _data()
    assert d["selection_bias"], "the selection bias section is what makes the frequencies usable"
    text = json.dumps(d["roll_table_weights"])
    assert "exclude" in text.lower() or "excluded" in text.lower(), \
        "the record must say the player-selected pet is excluded from the statistics"


def test_the_writeup_exists_and_agrees_with_the_data_on_s():
    """pet_tiers.md is the readable account. It must state the same S share as the measured record, since
    that is the one number a reader will carry away."""
    assert WRITEUP.exists(), "the readable write-up is part of documenting this"
    md = WRITEUP.read_text(encoding="utf-8")
    for token in ("SpeciesSeed", "GenusSeed", "CoreStatClassRollTable", "PetBattlerSeed"):
        assert token in md, f"the write-up must name {token}"
    assert "30, 30, 25, 15" in md, "the write-up must quote the roll table as read from game data"
    assert "15%" in md, "S is 15% per the game's own table; 7.4% was our superseded estimate"
    assert "1 in 296" in md, "the triple-S rarity follows from the real table"
    assert re.search(r"33%", md), "the write-up must contrast the tamed pets' inflated S rate"
    assert "pet feature" in md, "the codeword is how the user refers to this work"
