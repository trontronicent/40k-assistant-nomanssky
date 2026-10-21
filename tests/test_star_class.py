"""Star classes: the decoded weight table, the two tooltips built from it, and the shipped Codex document.

The weights are research - decoded once from the game's own
``biomelistperstartype.mbin`` into ``research/star_classes.json`` - so these tests pin the readings the
tooltips and the document quote, and the two slots the save measurement contradicts. Without that, a
re-decode with a shifted biome order would still look plausible while naming the wrong worlds.
"""
import json
from pathlib import Path

from nms_connector import star_class, worlds

RESEARCH = Path(__file__).resolve().parent.parent / "research" / "star_classes.json"
DOCUMENT = (Path(__file__).resolve().parent.parent / "codex" / "Reference"
            / "No Man's Sky Star Classes and Planet Classes.md")


def test_the_research_file_keeps_the_decoded_table_and_its_cross_check():
    """The file parses and still holds the seven rows (five star types plus the two yellow galaxy variants),
    each with its normal and prime weights, and the save measurement the document quotes. A truncated or
    re-decoded file would otherwise feed wrong worlds into every tooltip."""
    data = json.loads(RESEARCH.read_text(encoding="utf-8"))
    assert data["source_file"].endswith("biomelistperstartype.mbin")
    rows = data["weights"]
    assert set(rows) == {"Yellow", "Green", "Blue", "Red", "Purple",
                         "Yellow (empty galaxy)", "Yellow (lush galaxy)"}
    assert rows["Yellow"]["normal"]["Lush"] == 2.0, "lush worlds weigh double at a yellow star"
    assert rows["Yellow (lush galaxy)"]["normal"]["Lush"] == 4.0
    assert rows["Yellow (empty galaxy)"]["normal"]["Dead"] == 4.0
    assert rows["Red"]["prime"]["Exotic (red)"] == 3.0, "red exotics are a red star's prime planet"
    assert "Waterworld" in rows["Purple"]["normal"], "only the purple row lists water worlds"
    assert "Waterworld" not in rows["Yellow"]["normal"]
    check = data["save_cross_check"]
    assert check["Yellow"]["planets"] > 1000 and "Dead" not in check["Yellow"]["biomes"], (
        "the measurement that the Dead weight is not reflected in a real save")


def test_the_weight_row_follows_the_galaxy_kind():
    """A yellow star generates differently in a lush or an empty galaxy, and only there: Eissentam (index 9)
    is lush, Budullangr (6) empty, Euclid (0) normal, and no other colour has a variant row."""
    assert star_class.row_name("Yellow", 9) == "Yellow (lush galaxy)"
    assert star_class.row_name("Yellow", 6) == "Yellow (empty galaxy)"
    assert star_class.row_name("Yellow", 0) == "Yellow"
    assert star_class.row_name("Yellow", None) == "Yellow"
    assert star_class.row_name("Red", 9) == "Red", "only the yellow row has galaxy variants"
    assert star_class.weights("Yellow", 9)["Lush"] == 4.0
    assert star_class.weights("nonsense") == {}


def test_a_tooltip_names_only_worlds_the_table_is_trusted_for():
    """`favoured` lists what a star makes *more* likely than average and leaves out the two slots the save
    contradicts (Dead, Exotic) - the whole point of the measurement: a tooltip must not promise a dead world
    at a yellow star, where 2,673 recorded planets hold none."""
    assert star_class.favoured("Yellow") == ["Lush"], "Dead weighs 2 here and is still not named"
    red = star_class.favoured("Red")
    assert "Exotic (red) (as a prime planet)" in red and "Lava (as a prime planet)" in red
    assert not any(w.startswith("Exotic (as") or w == "Exotic" for w in red)
    assert len(star_class.favoured("Green")) <= star_class.MAX_WORLDS


def test_the_star_classes_of_a_world_type_are_only_the_telling_ones():
    """The other direction: a type every star generates at the same weight names no class at all (listing
    all five would say nothing), while a restricted or favoured type names them, heaviest first."""
    assert star_class.stars_for("Toxic") == [], "every star makes toxic worlds, equally"
    assert star_class.stars_for("Waterworld") == [("Purple", False)]
    assert star_class.stars_for("Lush") == [("Yellow", True)], "only the star that favours it"
    assert star_class.stars_for("Exotic (blue)")[0] == ("Blue", True)
    assert star_class.stars_for("Dead") == [] and star_class.stars_for(None) == []


def test_a_system_star_cell_carries_its_class_letters_drive_and_source():
    """The cell the page shows for a star: colour and class letters as the text, and a tooltip with the
    hyperdrive upgrade that reaches it, where the colour was read and that the digit and suffix mean nothing
    known. A colour the plugin has no class for keeps its text and gets no tooltip."""
    cell = star_class.star_cell("Red", 0, "read from the game's galaxy map")
    assert cell["text"] == "Red (class K or M)"
    assert "Cadmium Drive" in cell["hint"] and "read from the game's galaxy map" in cell["hint"]
    assert "no source confirms an effect in play" in cell["hint"]
    yellow = star_class.star_cell("Yellow", 0)
    assert "no upgrade needed" in yellow["hint"]
    assert star_class.star_cell(None) is None
    assert star_class.star_cell("Chartreuse") == "Chartreuse", "an unknown colour is still shown"


def test_a_planet_type_cell_explains_the_planetary_class():
    """A planet's Type cell keeps the game's own description as its text and explains in the tooltip what
    the class word means, what was recorded and which star classes make such a world."""
    cell = star_class.planet_type_cell("Frozen Planet", {"biome": "Frozen", "size": "Large"}, "cold worlds")
    assert cell["text"] == "Frozen Planet"
    assert "Planetary class" in cell["hint"] and "'Planet', 'Moon' or 'Planetoid'" in cell["hint"]
    assert "world type: Frozen, size class: Large" in cell["hint"]
    assert "Such worlds: cold worlds." in cell["hint"]
    water = star_class.planet_type_cell("Ocean World", {"biome": "Waterworld"})
    assert "Purple (class X or Y)" in water["hint"]
    assert star_class.planet_type_cell(None, {"biome": "Frozen"}) is None


def test_world_type_documents_name_the_star_classes_that_generate_them():
    """The generated Codex document of a world type gains the star-class line, so the knowledge is in the
    library and not only in a tooltip - and only for the types the table tells something about."""
    water = next(wt for wt in worlds.WORLD_TYPES if wt.id == "water")
    assert worlds._star_lines(water, lambda k, **v: v["s"])[0] == "Purple (class X or Y)"
    toxic = next(wt for wt in worlds.WORLD_TYPES if wt.id == "toxic")
    assert worlds._star_lines(toxic, lambda k, **v: v["s"]) == []
    lush = next(wt for wt in worlds.WORLD_TYPES if wt.id == "lush")
    assert "more likely" in worlds._star_lines(lush, lambda k, **v: v["s"])[0]


def test_the_shipped_codex_document_keeps_the_facts_and_their_limits():
    """The hand-written reference is what the persona answers spectral-class questions from. It must keep
    the class letters, the drives, and - the part that is easy to lose in an edit - that the letters are not
    in the game files and that the Dead and Exotic weights disagree with a real save."""
    text = DOCUMENT.read_text(encoding="utf-8")
    for needed in ("GLXY_ANALYSIS_SPECTRAL", "Cadmium Drive", "Emeril Drive", "Indium Drive", "Atlantid Drive",
                   "PLANETCLASS1", "BIOMELISTPERSTARTYPE.MBIN", "research/star_classes.json"):
        assert needed in text, f"the document lost {needed!r}"
    assert "letters are not in the game files" in text
    assert "Two slots disagree" in text and "not one" in text
    assert "2,673" in text, "the measurement's size is what makes the disagreement a finding"
