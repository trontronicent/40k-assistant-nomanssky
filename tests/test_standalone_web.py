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
