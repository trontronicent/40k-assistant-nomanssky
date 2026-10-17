"""The standalone page must look like the plugin page.

The app's plugin page is the reference: `frontend/src/components/plugins/PluginView.jsx`, `pluginModel.js`
and `TimersSection.jsx` in `J:\\40k-assistant`. The page here reproduces it as plain CSS and DOM, because
the install ships no build step, and keeping the two in step by hand is the price of that.

These tests pin the parts the page used to get wrong, with the app's own numbers and wording, so the next
change to either side has to be made on purpose. Like `test_standalone_web.py` they run the renderer under
Node, without a browser.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "standalone" / "web"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH")


def run_js(script: str):
    """Run a snippet with `sections.js` loaded as `S` and return the JSON it prints."""
    source = f"const S = require({json.dumps(str(WEB / 'sections.js'))});\n{script}"
    # UTF-8 explicitly: Node prints it, while this machine's console encoding is cp1252 and would turn
    # the sort arrows into question marks before any assertion saw them.
    out = subprocess.run([NODE, "-e", source], capture_output=True, text=True, timeout=30,
                         encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def css() -> str:
    return (WEB / "app.css").read_text(encoding="utf-8")


def test_a_table_switches_to_cards_on_exactly_the_app_s_thresholds():
    """`tableAsCards` is the app's rule, measured there and copied here: cards always under 560 px, at any
    width when the table needs 25 % more room than it has, and under 1024 px already at 10 % more. A page
    that switched at another width would read differently from the plugin page on the same phone."""
    result = run_js("console.log(JSON.stringify({"
                    "narrow: S.tableAsCards(400, 3, 0), twoCols: S.tableAsCards(400, 2, 0),"
                    "unmeasured: S.tableAsCards(0, 5, 9000), fits: S.tableAsCards(900, 5, 920),"
                    "overflow: S.tableAsCards(900, 5, 1000), wide: S.tableAsCards(1400, 5, 2299),"
                    "wideFits: S.tableAsCards(1400, 5, 1500),"
                    "breakpoint: S.CARD_BREAKPOINT, overflowMax: S.CARD_OVERFLOW_MAX}));")
    assert result["breakpoint"] == 560 and result["overflowMax"] == 1024
    assert result["narrow"] is True                 # a phone
    assert result["twoCols"] is False               # two columns always stay a table
    assert result["unmeasured"] is False            # nothing is decided before the box has a width
    assert result["fits"] is False                  # a table that nearly fits keeps its headers
    assert result["overflow"] is True               # 11 % over, under 1024 px: the cut-off Amount column
    assert result["wide"] is True                   # 2,299 px in a 1,374 px box: mostly behind a scroll
    assert result["wideFits"] is False


def test_a_card_is_the_row_with_the_first_cell_as_its_title():
    """One card per row: the first column is the title, every other column a label/value pair, and an
    empty cell is left out ("-" is a placeholder in a table and noise in a card) - the app's `cardFields`.
    A clickable row stays clickable as a card, or the phone layout loses the click."""
    section = {"type": "table", "columns": ["Name", "Amount", "Value", "Note"],
               "rows": [["Copper", "42", "\u2013", "ok"]], "row_keys": ["k1"], "row_action": "open",
               "row_hint": "Open this entry"}
    api = "{layout: 'cards', sortFor: () => null, onAction: () => {}, setSort: () => {}}"
    result = run_js(f"const f = S.nodeFactory();"
                    f"const node = S.BUILDERS.table(f, {json.dumps(section)}, {api});"
                    "console.log(JSON.stringify({html: S.toHtml(node)}));")
    html = result["html"]
    assert 'class="stc-card stc-clickable"' in html and 'role="button"' in html
    assert 'class="stc-card-title"' in html and ">Copper<" in html
    assert ">Amount<" in html and ">42<" in html
    assert ">Note<" in html                                   # a filled cell becomes a field
    assert ">Value<" not in html                              # the empty one does not
    assert 'title="Open this entry"' in html
    for rule in (".stc-cards {", ".stc-card {", ".stc-card-title {", ".stc-card-fields {"):
        assert rule in css(), rule


def test_the_card_layout_offers_the_sort_the_headers_would():
    """With no column headers to click, the app puts a "Sort by" select and a direction button above the
    cards. Picking a column sets the order outright (`setSort`) rather than cycling through it, which is
    what a select does - the cycling `onSort` would make the second tap mean "no order"."""
    section = {"type": "table", "columns": ["Name", "Amount", "Value"],
               "rows": [["a", "1", "x"], ["b", "2", "y"]]}
    api = ("{layout: 'cards', sortFor: () => ({column: 1, direction: 'asc'}), onAction: () => {},"
           " setSort: () => {}}")
    result = run_js(f"const f = S.nodeFactory();"
                    f"console.log(JSON.stringify({{html: S.toHtml(S.BUILDERS.table(f, "
                    f"{json.dumps(section)}, {api}))}}));")
    html = result["html"]
    assert 'class="stc-card-sort"' in html and ">Sort by<" in html
    assert "The plugin&#39;s order" in html and 'value="1" selected="selected"' in html
    assert 'class="stc-card-dir"' in html and "tap for descending" in html
    js = (WEB / "sections.js").read_text(encoding="utf-8")
    assert "api.setSort(section" in js
    assert "setSort: (section, sort)" in (WEB / "app.js").read_text(encoding="utf-8")


def test_a_column_header_shows_which_way_it_sorts():
    """The app draws a chevron in every header - faint until that column is the sorted one, then up or
    down, with the column itself in gold and the next click explained in the tooltip. Without it this
    page gave no sign at all of what had been sorted."""
    section = {"type": "table", "columns": ["Name", "Amount"], "rows": [["a", "1"], ["b", "2"]]}
    result = run_js(f"const f = S.nodeFactory(); const s = {json.dumps(section)};"
                    "const api = (sort) => ({sortFor: () => sort, onSort: () => {}, layout: 'table'});"
                    "console.log(JSON.stringify({"
                    "plain: S.toHtml(S.BUILDERS.table(f, s, api(null))),"
                    "asc: S.toHtml(S.BUILDERS.table(f, s, api({column: 1, direction: 'asc'}))),"
                    "desc: S.toHtml(S.BUILDERS.table(f, s, api({column: 1, direction: 'desc'})))}));")
    assert 'class="stc-sort-mark stc-sort-mark-off"' in result["plain"]
    assert 'aria-sort="none"' in result["plain"]
    assert "Sort by Amount, ascending" in result["plain"]
    assert 'class="stc-sorted"' in result["asc"] and 'aria-sort="ascending"' in result["asc"]
    assert "Sort by Amount, descending" in result["asc"]
    assert "\u2191" in result["asc"] and "\u2193" in result["desc"]
    assert "Show the rows in their original order" in result["desc"]
    assert ".stc-table th.stc-sorted" in css()


def test_a_table_has_a_head_and_a_body():
    """The rows went straight into `<table>`, so the browser invented a `tbody` around header and data
    alike. A real `thead` is what makes the sticky header a header and not the first row."""
    section = {"type": "table", "columns": ["A"], "rows": [["1"]]}
    result = run_js(f"const f = S.nodeFactory();"
                    f"console.log(JSON.stringify({{html: S.toHtml(S.BUILDERS.table(f, "
                    f"{json.dumps(section)}, {{sortFor: () => null, layout: 'table'}}))}}));")
    assert "<thead><tr><th" in result["html"] and "<tbody><tr><td" in result["html"]


def test_an_empty_or_cut_short_table_says_so():
    """The app shows the section's own `empty` line instead of an empty table, and names how many rows a
    truncated one has left. Both were silent here: an empty table looked like a rendering fault, and a
    cut-off list looked complete."""
    empty = {"type": "table", "columns": ["A"], "rows": [], "empty": "No systems yet."}
    cut = {"type": "table", "columns": ["A"], "rows": [["1"]], "truncated": True}
    plain = "{sortFor: () => null, layout: 'table'}"
    result = run_js("const f = S.nodeFactory();"
                    f"console.log(JSON.stringify({{"
                    f"empty: S.toHtml(S.BUILDERS.table(f, {json.dumps(empty)}, {plain})),"
                    f"cut: S.toHtml(S.BUILDERS.table(f, {json.dumps(cut)}, {plain})),"
                    "list: S.toHtml(S.BUILDERS.list(f, {type: 'list', items: []}))}));")
    assert "No systems yet." in result["empty"] and "<table" not in result["empty"]
    assert "Only the first 1 rows are shown." in result["cut"]
    assert "No entries." in result["list"]


def test_a_clickable_table_explains_the_click_above_it():
    """`row_hint` is a line over the table in the app, not only a tooltip on the first cell: a user who
    never hovers (a phone) otherwise never learns that a row opens something."""
    section = {"type": "table", "columns": ["A"], "rows": [["1"]], "row_keys": ["k"],
               "row_action": "open", "row_hint": "Click a system to see its map"}
    result = run_js(f"const f = S.nodeFactory();"
                    f"console.log(JSON.stringify({{html: S.toHtml(S.BUILDERS.table(f, "
                    f"{json.dumps(section)}, {{sortFor: () => null, layout: 'table', onAction: () => {{}}}}"
                    f"))}}));")
    assert '<div class="stc-hint">Click a system to see its map</div>' in result["html"]
    assert ".stc-hint {" in css()


def test_a_short_cell_never_wraps_and_a_long_one_does():
    """The app puts the decision on the `<td>`: a cell of at most 30 characters gets `white-space: nowrap`
    and no minimum width, a longer one wraps inside a 20ch column. Here the class sat on the text inside
    the cell, together with a 14ch rule the app does not have, so the columns came out at other widths -
    and a key/value entry, which wraps freely in the app, was held at 14ch too."""
    section = {"type": "table", "columns": ["A"], "rows": [["short"], ["x" * 40]]}
    result = run_js(f"const f = S.nodeFactory();"
                    f"const t = S.toHtml(S.BUILDERS.table(f, {json.dumps(section)}, "
                    "{sortFor: () => null, layout: 'table'}));"
                    "const kv = S.toHtml(S.BUILDERS.kv(f, {type: 'kv', items: [{label: 'a', value: 'b'}]}));"
                    "console.log(JSON.stringify({table: t, kv: kv, nowrap: S.cellNoWrap('short'),"
                    " wraps: S.cellNoWrap('x'.repeat(40))}));")
    assert result["nowrap"] is True and result["wraps"] is False
    assert '<td class="stc-nowrap">' in result["table"]
    assert "<td>" in result["table"]                      # the long cell claims the 20ch minimum
    assert "stc-nowrap" not in result["kv"]
    assert "min-width: 20ch;" in css()
    assert "td span { min-width: 14ch" not in css()


def test_a_stat_shows_its_own_explanation():
    """A `stats` item may carry a `hint`; the app shows it as a tooltip and this page dropped it, so the
    same number was explained in one host and bare in the other."""
    section = {"type": "stats", "items": [{"label": "Units", "value": 42, "hint": "What you can spend"}]}
    result = run_js(f"const f = S.nodeFactory();"
                    f"console.log(JSON.stringify({{html: S.toHtml(S.BUILDERS.stats(f, "
                    f"{json.dumps(section)}))}}));")
    assert 'title="What you can spend"' in result["html"]


def test_a_timer_is_a_row_with_its_end_time_as_in_the_app():
    """The app's timer is a row with a hairline under it: what it is on the left, the countdown and when
    it ends on the right, the progress bar across the bottom. This page drew a bordered card without the
    end time at all."""
    section = {"type": "timers", "items": [{"key": "t1", "label": "Frigate", "detail": "3 ships",
                                            "ends_at": 4000000000, "started_at": 3999000000}]}
    result = run_js(f"const f = S.nodeFactory();"
                    f"const node = S.BUILDERS.timers(f, {json.dumps(section)}, "
                    "{formatRemaining: () => '1 h 33 min', formatEndLabel: () => 'ends tomorrow 05:00'});"
                    "const none = S.BUILDERS.timers(f, {type: 'timers', items: []}, "
                    "{formatRemaining: () => '', formatEndLabel: () => ''});"
                    "console.log(JSON.stringify({html: S.toHtml(node), none: S.toHtml(none)}));")
    html = result["html"]
    assert 'class="stc-timer-when"' in html and "ends tomorrow 05:00" in html
    assert 'class="stc-timer-remaining"' in html and "1 h 33 min" in html
    assert 'class="stc-timer-detail"' in html and 'data-started-at="3999000000"' in html
    assert "No timers running." in result["none"]
    assert ".stc-timer-at {" in css() and ".stc-timer-done {" in css()


def test_the_countdown_and_the_end_time_read_as_in_the_app():
    """`formatRemaining` is the app's `formatDuration` and `endLabel` its `formatEndTime`: the same
    wording, so a frigate expedition does not say "33:20" here and "33 min 20 s" in the app."""
    timers = json.dumps(str(WEB / "timers.js"))
    result = run_js(f"const T = require({timers});"
                    "const at = 1760000000;"
                    "console.log(JSON.stringify({"
                    "secs: T.formatRemaining({ends_at: at + 45}, at),"
                    "mins: T.formatRemaining({ends_at: at + 245}, at),"
                    "hours: T.formatRemaining({ends_at: at + 5600}, at),"
                    "days: T.formatRemaining({ends_at: at + 183600}, at),"
                    "done: T.formatRemaining({ends_at: at - 5}, at),"
                    "ended: T.endLabel({ends_at: at - 5}, at).slice(0, 6),"
                    "ends: T.endLabel({ends_at: at + 45}, at).slice(0, 5)}));")
    assert result == {"secs": "45 s", "mins": "4 min 05 s", "hours": "1 h 33 min", "days": "2 d 3 h",
                      "done": "done", "ended": "ended ", "ends": "ends "}


def test_the_page_decides_the_table_layout_after_rendering_and_on_a_resize():
    """`measureTables` is this page's stand-in for the app's ResizeObserver: a table only has a width once
    it is in the document, so the layout is decided there and again when the window changes. Without the
    resize pass, turning a phone would leave the previous layout behind."""
    app_js = (WEB / "app.js").read_text(encoding="utf-8")
    assert "window.Sections.measureTables(host)" in app_js
    assert 'addEventListener("resize"' in app_js and "clearTimeout(resizing)" in app_js
    js = (WEB / "sections.js").read_text(encoding="utf-8")
    assert "function measureTables(" in js and "neededWidths" in js


def test_the_fonts_the_page_names_are_the_fonts_it_loads():
    """A font named in a rule but missing from the import falls back to the system's, which is what
    happened to the copy blocks: they ask for Roboto Mono, the app loads it, this page did not. The same
    for a colour variable: `--text-muted` was never defined here."""
    imported = css().split("@import url('")[1].split("');")[0]
    for family in ("Cinzel", "Chakra+Petch", "Inter", "Roboto+Mono"):
        assert family in imported, family
    assert "var(--text-muted)" not in css()


def test_a_text_section_keeps_the_spacing_it_was_given():
    """`pre-wrap`, as in the app: an exported table lines up with runs of spaces, and `pre-line` - what
    this page used - collapses them."""
    rule = next(line for line in css().splitlines() if line.startswith(".stc-text {"))
    assert "pre-wrap" in rule


def test_the_about_tab_renders_in_this_page_too():
    """The credits are a tab of the connector's own view (`nms_connector/credits.py`), so both hosts show
    them; this asserts the page actually draws what that tab is made of."""
    from nms_connector import credits
    view = {"sections": credits.sections("1.2.3", "standalone")}
    result = run_js(f"const r = S.renderSections({json.dumps(view, ensure_ascii=False)}, "
                    "{layout: 'table', sortFor: () => null});"
                    "console.log(JSON.stringify({types: r.types, html: r.html}));")
    assert result["types"].count("table") == len(credits.GROUPS)
    assert credits.AUTHOR in result["html"]
    assert "LGPL-3.0" in result["html"] and "pystray" in result["html"]


def test_a_table_remembers_how_much_room_it_wanted():
    """A box showing cards has no table to measure, so `measureTables` falls back on what that section
    needed when it last was a table. Without the memory the page would find that the table fits, swap
    back, measure, swap to cards again - a flicker on every five-second poll. Only a section with an id
    can be remembered; an id-less one would otherwise share an entry with every other id-less table."""
    result = run_js("console.log(JSON.stringify({"
                    "noId: S.neededFor('', 1200), first: S.neededFor('t1', 1200),"
                    "remembered: S.neededFor('t1', 0), unknown: S.neededFor('t2', 0)}));")
    assert result == {"noId": 1200, "first": 1200, "remembered": 1200, "unknown": 0}


def test_the_scrolling_boxes_have_the_app_s_hairline_scrollbars():
    """The app's plugin tables carry `.strategic-scroll-both`: a thin gold scrollbar on a transparent
    track. A default Windows scrollbar inside a dark gold panel is the most visible difference there is,
    and the boxes that scroll here are the table box, the card grid and a copyable text block."""
    rules = css()
    assert "scrollbar-color: rgba(var(--gold-rgb), 0.35) transparent;" in rules
    assert "color-scheme: dark;" in rules
    for box in (".stc-table-box", ".stc-cards", ".stc-copy-block"):
        assert box + "::-webkit-scrollbar-thumb" in rules, box
