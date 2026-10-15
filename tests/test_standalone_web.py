"""The standalone page's pure renderer, exercised under Node (no browser, like the app's frontend tests)."""
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
    out = subprocess.run([NODE, "-e", source], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_every_section_type_renders():
    """The context advertises eleven section types; one the page cannot draw would show as a blank gap in
    the real view, so each is rendered here and asserted to produce a node."""
    view = {"sections": [
        {"type": "notice", "text": "x"}, {"type": "stats", "items": [{"label": "a", "value": 1}]},
        {"type": "kv", "items": [{"label": "a", "value": "b"}]},
        {"type": "table", "columns": ["A"], "rows": [["1"]]},
        {"type": "list", "items": ["a"]}, {"type": "text", "text": "a"},
        {"type": "form", "action": "x", "fields": [{"id": "q", "label": "Q", "type": "text"}]},
        {"type": "timers", "items": [{"key": "t", "label": "T", "ends_at": 4000000000}]},
        {"type": "orbit", "center": {"label": "Star"}, "bodies": [{"label": "P1"}]},
        {"type": "starmap", "points": [{"key": "a", "label": "A", "x": 0, "y": 0, "z": 0}]},
        {"type": "tabs", "tabs": [{"id": "t1", "label": "One", "sections": [{"type": "text", "text": "in"}]}]},
    ]}
    result = run_js(f"const r = S.renderSections({json.dumps(view)}); "
                    "console.log(JSON.stringify({count: r.children.length, types: r.types}));")
    assert result["count"] == 11
    assert "starmap" in result["types"]


def test_an_unknown_section_type_is_skipped_not_guessed():
    """A newer connector may send a type this page does not know; it must be left out quietly rather than
    rendered as junk - and `tests/test_host_contract.py` is what stops that from happening unnoticed."""
    view = {"sections": [{"type": "hologram", "text": "x"}, {"type": "text", "text": "ok"}]}
    result = run_js(f"const r = S.renderSections({json.dumps(view)}); "
                    "console.log(JSON.stringify(r.types));")
    assert result == ["text"]


def test_plugin_text_is_never_html():
    """A table cell containing markup must appear as text. The app's renderer is guarded against
    `dangerouslySetInnerHTML`; the standalone page must be guarded the same way."""
    view = {"sections": [{"type": "table", "columns": ["A"], "rows": [["<b>bold</b>"]]}]}
    result = run_js(f"const r = S.renderSections({json.dumps(view)}); "
                    "console.log(JSON.stringify({html: r.html}));")
    assert "&lt;b&gt;" in result["html"]
    assert "<b>bold</b>" not in result["html"]


def test_icon_cell_points_at_the_asset_route():
    """Icon cells are `{text, icon}`; the page must fetch the PNG from `/api/assets/<name>` and keep the
    text, or inventories lose both their pictures and their names."""
    assert run_js('console.log(JSON.stringify(S.cellIcon({text: "Copper", icon: "copper.png"})));') \
        == "/api/assets/copper.png"


def test_icon_name_is_validated():
    """An icon name outside the app's `ICON_NAME_RE` must fall back to plain text instead of building a
    URL out of plugin data."""
    assert run_js('console.log(JSON.stringify(S.cellIcon({text: "x", icon: "../secret.png"})));') is None


def test_sort_is_numeric_where_the_text_is_a_number():
    """Amount columns hold `84'308` and `31 %`. Sorting them as text puts 9 above 84,308, which is why the
    app has `pluginModel.sortKey`; the standalone page copies that rule."""
    assert run_js("console.log(JSON.stringify(S.sortRows([[\"9\"],[\"84'308\"],[\"31 %\"]], 0, 'asc')));") \
        == [0, 2, 1]


def test_empty_cells_sort_last_in_both_directions():
    """A dash or a null is "no value", not a small one; the app sorts them last either way so a column of
    mostly-empty cells stays readable."""
    assert run_js('console.log(JSON.stringify(S.sortRows([["\\u2013"],["2"],["1"]], 0, "asc")));') == [2, 1, 0]
    assert run_js('console.log(JSON.stringify(S.sortRows([["\\u2013"],["2"],["1"]], 0, "desc")));') == [1, 2, 0]


def test_a_cell_may_name_its_own_sort_value():
    """Wealth and Conflict columns carry `{text, sort}` because ranked words must not sort
    alphabetically; a finite numeric `sort` wins over the text."""
    assert run_js('console.log(JSON.stringify(S.sortRows([[{text:"Poor",sort:1}],'
                  '[{text:"Average",sort:2}]], 0, "desc")));') == [1, 0]


def test_focus_selects_every_tab_on_the_way():
    """An action answering `{focus: "system-map"}` must open each tab containing that section - the app's
    `findSectionPath` behaviour, without which a row click appears to do nothing."""
    view = {"sections": [{"type": "tabs", "tabs": [
        {"id": "main", "label": "M", "sections": [{"type": "tabs", "tabs": [
            {"id": "sys", "label": "S", "sections": [{"type": "text", "id": "system-map", "text": "x"}]}]}]}]}]}
    assert run_js(f"console.log(JSON.stringify(S.tabPath({json.dumps(view)}, 'system-map')));") \
        == ["main", "sys"]


def test_form_values_survive_a_view_poll():
    """The page polls the view every 5 s. A field that adopted the plugin's value on every poll would wipe
    what the user is typing - the lesson behind the app's `useFormValues`."""
    result = run_js("S.setFormValue('f1', 'q', 'Kupfer');"
                    "const first = S.formValues('f1', [{id:'q', value:''}]);"
                    "const again = S.formValues('f1', [{id:'q', value:''}]);"
                    "console.log(JSON.stringify([first.q, again.q]));")
    assert result == ["Kupfer", "Kupfer"]


def test_a_changed_plugin_value_is_adopted():
    """When the plugin itself changes a field's value (a reset after a search), the page must follow -
    only an unchanged plugin value is ignored."""
    result = run_js("S.setFormValue('f2', 'q', 'old');"
                    "S.formValues('f2', [{id:'q', value:'start'}]);"
                    "const after = S.formValues('f2', [{id:'q', value:'fromPlugin'}]);"
                    "console.log(JSON.stringify(after.q));")
    assert result == "fromPlugin"


def test_every_section_is_a_card_whose_head_carries_its_title():
    """The app wraps each section in a card with a head strip holding the title (PluginView's SectionList);
    the page does the same, and the section's id stays on the *outer* node, which is what a `focus` answer
    scrolls to. A title drawn inside the box instead would read as part of the content."""
    view = {"sections": [{"type": "table", "id": "t1", "title": "Visited systems",
                          "columns": ["A"], "rows": [["1"]]}]}
    result = run_js(f"const r = S.renderSections({json.dumps(view)});"
                    "const card = r.children[0];"
                    "console.log(JSON.stringify({cls: card.attrs.class, id: card.attrs['data-section-id'],"
                    " head: card.children[0].attrs.class, title: card.children[0].textContent,"
                    " body: card.children[1].attrs.class, inner: card.children[1].children[0].attrs.class}));")
    assert result == {"cls": "stc-section", "id": "t1", "head": "stc-section-head",
                      "title": "Visited systems", "body": "stc-section-body", "inner": "stc-table-box"}
    # A section without a title gets the card, but no empty head strip.
    plain = run_js("const r = S.renderSections({sections: [{type: 'text', text: 'x'}]});"
                   "console.log(JSON.stringify(r.children[0].children.map((c) => c.attrs.class)));")
    assert plain == ["stc-section-body"]


def test_a_notice_and_a_tab_strip_are_not_carded():
    """The two the app leaves bare: a notice is its own bordered line in its level's colour (the sign comes
    from the CSS, so the text sits in a box of its own), and a tab strip must not look like a section."""
    view = {"sections": [{"type": "notice", "level": "warn", "text": "careful"},
                         {"type": "tabs", "tabs": [{"id": "a", "label": "A", "sections": []}]}]}
    result = run_js(f"const r = S.renderSections({json.dumps(view)});"
                    "console.log(JSON.stringify(r.children.map((c) => c.attrs.class)));")
    assert result == ["stc-notice stc-notice-warn", "stc-tabs"]
    text = run_js(f"const r = S.renderSections({json.dumps(view)});"
                  "console.log(JSON.stringify({box: r.children[0].children[0].attrs.class,"
                  " text: r.children[0].children[0].children[0].textContent}));")
    assert text == {"box": "stc-notice-text", "text": "careful"}


def test_nested_tabs_are_drawn_as_the_apps_sub_tabs():
    """The app draws the first level of tabs as an underlined strip and every deeper level as bordered
    chips, which is how the Systems and Saves tabs read as *inside* their tab rather than beside it."""
    view = {"sections": [{"type": "tabs", "tabs": [
        {"id": "outer", "label": "Outer", "sections": [
            {"type": "tabs", "tabs": [{"id": "inner", "label": "Inner", "sections": [
                {"type": "text", "text": "deep"}]}]}]}]}]}
    result = run_js(f"const r = S.renderSections({json.dumps(view)});"
                    "const outer = r.children[0];"
                    "const panel = outer.children[1].children[0].children[0];"
                    "console.log(JSON.stringify({top: outer.children[0].attrs.class,"
                    " sub: panel.children[0].attrs.class}));")
    assert result == {"top": "stc-tabstrip", "sub": "stc-tabstrip stc-subtabs"}


def test_the_stylesheet_uses_the_apps_own_tokens():
    """The look is the app's, so the page's colours are the app's `index.css` values. This guard fails if
    the old standalone palette (--bg/--panel/--accent) comes back, which is how the two would drift apart
    unnoticed - there is no shared stylesheet to keep them together."""
    css = (WEB / "app.css").read_text(encoding="utf-8")
    for token, value in (("--void", "#050508"), ("--void-alt", "#08070f"), ("--void-surface", "#0d0b18"),
                         ("--gold", "#c8972a"), ("--gold-bright", "#f0bb42"), ("--gold-rgb", "200, 151, 42"),
                         ("--mech-red", "#c41e0a"), ("--text-primary", "#f1f5f9"),
                         ("--text-secondary", "#94a3b8"), ("--text-dim", "#475569")):
        assert f"{token}: {value};" in css, token
    for gone in ("--panel:", "--panel-2:", "--accent:", "--accent-2:", "--line:", "--muted:"):
        assert gone not in css, gone
    for shape in (".stc-section {", ".stc-section-head {", ".stc-section-body {", ".stc-subtabs {",
                  ".view-head {", ".view-actions {"):
        assert shape in css, shape
    assert "Chakra Petch" in css and "Cinzel" in css and "Inter" in css


def test_the_page_has_the_views_own_header_and_action_buttons():
    """The app's plugin page shows the view's title and subtitle and one button per action; the standalone
    page had neither, so *Rescan*, *Scan game now* and the rest were unreachable outside the tray. The
    markup and the wiring are asserted here (there is no browser in the suite)."""
    html = (WEB.parent / "web" / "index.html").read_text(encoding="utf-8")
    for element in ('id="view-head"', 'id="view-title"', 'id="view-subtitle"', 'id="view-actions"',
                    'id="view-sections"'):
        assert element in html, element
    app_js = (WEB / "app.js").read_text(encoding="utf-8")
    assert "drawViewHead" in app_js and "view-actions" in app_js
    # A destructive action asks first (the app's rule for ACTIONS entries carrying `confirm`).
    assert "action.confirm" in app_js and "window.confirm" in app_js
    # The buttons are disabled while one runs, as the app disables them through busyAction.
    assert "disabled = true" in app_js


def test_a_row_menu_is_wired_and_its_helpers_match_the_apps():
    """app 3.18.0: a table's `row_menu` becomes a right-click menu. The two pure helpers are the app's
    (`pluginModel.rowMenuItems` / `menuPosition`) so the two hosts place and bound it the same way, and the
    menu is appended to the body - the table box scrolls and would clip it."""
    result = run_js("console.log(JSON.stringify({"
                    "items: S.rowMenuItems({row_menu: [{id: 'a', label: 'A', description: 'd'}, {id: 'b'},"
                    " {label: 'no id'}]}),"
                    "none: S.rowMenuItems({}),"
                    "right: S.menuPosition(1800, 100, {width: 220, height: 160}, {width: 1920, height: 1080}),"
                    "bottom: S.menuPosition(100, 1000, {width: 220, height: 160}, {width: 1920, height: 1080}),"
                    "tiny: S.menuPosition(10, 10, {width: 220, height: 160}, {width: 200, height: 150})}));")
    assert result["items"] == [{"id": "a", "label": "A", "description": "d"},
                              {"id": "b", "label": "b", "description": None}]
    assert result["none"] == []
    assert result["right"] == {"left": 1580, "top": 100} and result["bottom"] == {"left": 100, "top": 840}
    assert result["tiny"] == {"left": 8, "top": 8}

    js = (WEB / "sections.js").read_text(encoding="utf-8")
    assert 'addEventListener("contextmenu"' in js and "doc.body.appendChild(box)" in js
    assert "closeRowMenu" in js and '"Escape"' in js          # a click, a scroll or Escape closes it
    app_js = (WEB / "app.js").read_text(encoding="utf-8")
    assert "copyText" in app_js and "navigator.clipboard" in app_js and 'execCommand("copy")' in app_js
    assert "refused the clipboard" in app_js
    css = (WEB / "app.css").read_text(encoding="utf-8")
    assert ".stc-row-menu {" in css and ".stc-row-menu-item {" in css
