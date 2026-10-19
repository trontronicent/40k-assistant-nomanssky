"""The standalone page's Markdown renderer (standalone/web/markdown.js): Codex hits are drawn styled, like the
app draws them, built from DOM nodes - never from HTML. Run under Node, like the rest of the page's tests."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "standalone" / "web"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH")

DOC = ("## Warp Cell\n**Warp Cell** is crafted from `ANTIMATTER` and *Antimatter Housing* ([more](x)).\n"
       "- one\n  - nested FOOD_DNUT_1\n1. first\n\n| Item | Value |\n|---|---|\n| Warp Cell | 46,750 |\n"
       "> a quote\n---\n```\ncode | <b>not</b> a table\n```\nlast line")


def render(text: str, terms=None) -> str:
    """The HTML the renderer's nodes stand for (sections.js's fake document and toHtml)."""
    script = (f"const S = require({json.dumps(str(WEB / 'sections.js'))});"
              f"const M = require({json.dumps(str(WEB / 'markdown.js'))});"
              f"console.log(JSON.stringify(S.toHtml(M.renderMarkdown(S.nodeFactory(), {json.dumps(text)}, "
              f"{json.dumps(terms or [])}))));")
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_codex_markdown_is_drawn_styled():
    """Headings, bold, italic, code, links (text only), nested and numbered lists, tables with a header row,
    quotes, rules and fenced code become their elements - a hit reads like the document, not like its source."""
    html = render(DOC)
    assert html.startswith('<div class="md"><h2>Warp Cell</h2><p><strong>Warp Cell</strong> is crafted from '
                           "<code>ANTIMATTER</code> and <em>Antimatter Housing</em> (more).</p>")
    assert '<ul class="md-level-0"><li>one</li></ul><ul class="md-level-1"><li>nested FOOD_DNUT_1</li></ul>' in html
    assert '<ol class="md-level-0"><li>first</li></ol>' in html
    assert "<table><tr><th>Item</th><th>Value</th></tr><tr><td>Warp Cell</td><td>46,750</td></tr></table>" in html
    assert "<blockquote>a quote</blockquote><hr>" in html
    assert "<pre><code>code | &lt;b&gt;not&lt;/b&gt; a table</code></pre><p>last line</p></div>" in html


def test_markup_in_codex_text_stays_text():
    """Codex text is user and plugin text: an HTML tag in it is shown as written, never interpreted."""
    html = render("<img src=x onerror=alert(1)> **<i>bold</i>**")
    assert "<img" not in html and "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "<strong>&lt;i&gt;bold&lt;/i&gt;</strong>" in html


def test_the_searched_words_are_marked_where_a_word_starts():
    """The words typed into the search are marked at word starts in any case ("warp" marks Warp and warp, not
    'hyperwarp'), also inside bold text and table cells; regex characters in a word are taken literally."""
    html = render("**Warp** cell and hyperwarp\n\n| warp |\n|---|", ["warp", "a+"])
    assert "<strong><mark>Warp</mark></strong> cell and hyperwarp" in html
    assert "<th><mark>warp</mark></th>" in html


def test_a_long_hit_is_cut_after_a_whole_line():
    """A long document is cut after the last whole line within the limit (a table row is never cut in half)."""
    script = (f"const M = require({json.dumps(str(WEB / 'markdown.js'))});"
              "console.log(JSON.stringify([M.leadingLines('| a | b |\\n| c | d |\\n| e | f |', 20),"
              " M.leadingLines('short', 20)]));")
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, encoding="utf-8")
    assert json.loads(out.stdout) == ["| a | b |\n| c | d |\n\n…", "short"]


def test_the_codex_panel_draws_hits_with_the_renderer():
    """The Codex panel renders a hit through markdown.js (loaded before panels.js), not as a raw text paragraph."""
    panels = (WEB / "panels.js").read_text(encoding="utf-8")
    assert "window.Markdown.renderMarkdown(document" in panels and 'el("p", null, hit.text' not in panels
    page = (WEB / "index.html").read_text(encoding="utf-8")
    assert page.index('src="markdown.js"') < page.index('src="panels.js"')
    assert not re.search(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML", (WEB / "markdown.js").read_text(encoding="utf-8"))
