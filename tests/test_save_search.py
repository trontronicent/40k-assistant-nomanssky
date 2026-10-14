"""Tests for the one search box over everything in the save (save_search.py and the Overview section):
the groups it searches, the matching, the caps and what the page shows for a query that finds nothing."""

from nms_connector import planet_search, save_search

SECTIONS = [
    {"type": "notice", "level": "info", "text": "ignored"},
    {"type": "tabs", "id": "main", "tabs": [
        {"id": "systems", "label": "Systems", "sections": [
            {"type": "table", "id": "visited", "title": "Visited systems", "columns": ["System", "Economy"],
             "rows": [["Delta Sol", "Mining (Bergbau)"], ["Kayana", "Trading (Handel)"]],
             "row_keys": ["62", "b5"], "row_action": "open_system", "row_hint": "Click a system"},
            {"type": "form", "id": "a-form", "fields": []},
            {"type": "table", "title": "Empty", "columns": ["X"], "rows": []},
        ]},
        {"id": "inventory", "label": "Inventory", "sections": [
            {"type": "table", "title": "Exosuit inventory", "columns": ["Name", "Amount"],
             "rows": [[{"text": "Copper (Kupfer)", "icon": "y.png"}, 581], ["Sodium (Natrium)", 12]]},
        ]},
    ]},
]


def groups():
    return save_search.groups_from_sections(SECTIONS)


def test_the_search_groups_are_the_tables_the_page_already_built():
    """Every kind is searched through the table its own tab shows - nothing is indexed twice, and a table
    that gains a column is searchable at once. Forms and empty tables are not groups."""
    titles = [g.title for g in groups()]
    assert titles == ["Visited systems", "Exosuit inventory"]
    assert groups()[0].row_action == "open_system" and groups()[0].keys == ["62", "b5"]
    assert groups()[1].row_action is None
    # A section id can be skipped - the search's own results table, which would otherwise be searched again.
    assert [g.title for g in save_search.groups_from_sections(SECTIONS, skip=("visited",))] == ["Exosuit inventory"]


def test_a_row_matches_when_every_word_matches_one_of_its_cells():
    """The matching is the planet search's, over the row's cells: either language, a word finds longer ones,
    an icon cell by its text, and every word must match - the words of one query belong together."""
    assert [f.group.title for f in save_search.search(groups(), "kupfer")] == ["Exosuit inventory"]
    assert [f.group.title for f in save_search.search(groups(), "kupf")] == ["Exosuit inventory"]
    assert [f.group.title for f in save_search.search(groups(), "bergbau")] == ["Visited systems"]
    assert save_search.search(groups(), "delta kayana") == []        # both words, no row has both
    assert save_search.search(groups(), "") == [] and save_search.search(groups(), "ab") == []
    assert save_search.search([], "kupfer") == []

    found = save_search.search(groups(), "delta")[0]
    assert found.total == 1 and found.rows == [["Delta Sol", "Mining (Bergbau)"]] and found.keys == ["62"]
    # A word that matches rows of two kinds reports both, the kind with more hits first.
    both = save_search.search(groups(), "a")           # too short to be a search word at all
    assert both == []


def test_the_kinds_with_the_most_hits_come_first_and_each_is_capped():
    """The box searches everything, so the result has to stay readable: at most MAX_PER_GROUP rows per kind
    (the count still says how many there are) and at most MAX_GROUPS kinds, most hits first."""
    many = save_search.Group(title="Planets", columns=["Planet"],
                             rows=[[f"Copper World {i}"] for i in range(save_search.MAX_PER_GROUP + 10)])
    one = save_search.Group(title="Ships", columns=["Ship"], rows=[["Copper Falcon"]])
    results = save_search.search([one, many], "copper")
    assert [f.group.title for f in results] == ["Planets", "Ships"]
    assert results[0].total == save_search.MAX_PER_GROUP + 10
    assert len(results[0].rows) == save_search.MAX_PER_GROUP

    crowd = [save_search.Group(title=f"Kind {i}", columns=["X"], rows=[["copper"]]) for i in range(12)]
    assert len(save_search.search(crowd, "copper")) == save_search.MAX_GROUPS


def test_the_page_shows_one_table_per_kind_and_says_so_when_nothing_matches():
    """Each kind's hits keep their own columns and their click target, the first table carries the id the
    page scrolls to, and a query that matches nothing says what to try instead of showing an empty table."""
    results = save_search.search(groups(), "copper")
    sections = save_search.sections(results, "copper")
    assert sections[0]["id"] == save_search.RESULTS_ID
    assert sections[0]["title"] == "Exosuit inventory: 1 match(es)"
    assert sections[0]["columns"] == ["Name", "Amount"] and "row_action" not in sections[0]
    assert save_search.summary(results, "copper") == '1 match(es) for "copper" in 1 kind(s): Exosuit inventory 1.'

    clickable = save_search.sections(save_search.search(groups(), "sol"), "sol")[0]
    assert clickable["row_action"] == "open_system" and clickable["row_keys"] == ["62"]
    assert clickable["row_hint"] == "Click a system"

    nothing = save_search.sections([], "nonsense")
    assert nothing[0]["type"] == "notice" and "nonsense" in nothing[0]["text"]
    assert save_search.sections([], "") == []


def test_a_capped_group_says_how_many_it_shows():
    """A kind with more hits than rows shown says so in its title, as the two older searches do."""
    many = save_search.Group(title="Planets", columns=["Planet"],
                             rows=[[f"Copper World {i}"] for i in range(save_search.MAX_PER_GROUP + 5)])
    table = save_search.sections(save_search.search([many], "copper"), "copper")[0]
    assert table["title"] == f"Planets: {save_search.MAX_PER_GROUP + 5} match(es) - the first {save_search.MAX_PER_GROUP}"


def test_row_words_reads_every_kind_of_cell():
    """A row's searchable words are its cells' texts: plain values, numbers, an {text, icon} item cell, a
    {text, sort} ranked cell, and None for an empty one."""
    words = save_search.row_words(["Delta Sol", 581, None, {"text": "★★☆ Average", "sort": 2},
                                   {"text": "Copper (Kupfer)", "icon": "y.png"}])
    assert {"delta", "sol", "581", "average", "copper", "kupfer"} <= words
    assert save_search.row_words([]) == set()
    assert planet_search.cell_text(None) == "" and planet_search.cell_text({"text": "x"}) == "x"


def test_the_overview_has_the_search_box_and_the_action_stores_the_text(tmp_path, monkeypatch):
    """The box sits on the Overview tab; the action keeps the (untrusted, cut) text and the view built right
    after it does the searching, so the search follows every poll of the page without being re-run here."""
    import asyncio

    from nms_connector import create_plugin
    from test_connector import FakeCtx

    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))
    plugin = create_plugin(FakeCtx(tmp_path / "data"))
    form = plugin.page.save_search_sections([])[0]
    assert form["id"] == save_search.FORM_ID and form["action"] == save_search.SEARCH_SAVE
    assert form["fields"][0]["value"] == ""

    answer = asyncio.run(plugin.action(save_search.SEARCH_SAVE, {"query": "  Kupfer " + "x" * 200}))
    assert answer["ok"] and answer["focus"] == save_search.RESULTS_ID
    assert len(plugin.save_query) == save_search.MAX_QUERY_CHARS and plugin.save_query.startswith("Kupfer")
    assert plugin.page.save_search_sections([])[0]["fields"][0]["value"] == plugin.save_query

    cleared = asyncio.run(plugin.action(save_search.SEARCH_SAVE, {"query": ""}))
    assert cleared["message"] == "Search cleared." and plugin.save_query == ""
    # With a query, the sections are the form, the summary line and one table per kind.
    plugin.save_query = "delta"
    kinds = plugin.page.save_search_sections(SECTIONS[1]["tabs"])
    assert [s["type"] for s in kinds] == ["form", "text", "table"]
    assert kinds[2]["rows"] == [["Delta Sol", "Mining (Bergbau)"]]
