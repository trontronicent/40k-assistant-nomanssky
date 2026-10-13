"""The alert rule, shared by the tray (Python) and the page (JavaScript).

One table of cases drives both implementations: a timer announced twice in the page and never in the
tray is exactly the kind of bug nobody reports.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from standalone import alerts

ROOT = Path(__file__).resolve().parent.parent
TIMERS_JS = ROOT / "standalone" / "web" / "timers.js"
CASES = json.loads((Path(__file__).parent / "alert_cases.json").read_text(encoding="utf-8"))
NODE = shutil.which("node")


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_python_matches_the_table(case):
    """The Python side is what notifies when no page is open, so it must behave exactly like the page the
    user saw yesterday."""
    state = alerts.new_state()
    fired = []
    for step in case["steps"]:
        fired.append([t["key"] for t in alerts.due(state, step["timers"], step["now"])])
    assert fired == case["expected"]


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_javascript_matches_the_same_table(case):
    """Two implementations of one rule drift silently; the table is the contract between them."""
    script = (
        f"const M = require({json.dumps(str(TIMERS_JS))});"
        f"const c = {json.dumps(case)};"
        "const s = M.newState(); const out = [];"
        "for (const step of c.steps) out.push(M.due(s, step.timers, step.now).map(t => t.key));"
        "console.log(JSON.stringify(out));"
    )
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == case["expected"]


def test_the_two_implementations_agree_on_the_grace_window():
    """`GRACE_S` decides what counts as news; a different value on either side would make the tray and
    the page disagree about the same timer."""
    if NODE is None:
        pytest.skip("node is not on PATH")
    script = f"const M = require({json.dumps(str(TIMERS_JS))}); console.log(JSON.stringify(M.GRACE_S));"
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert json.loads(out.stdout) == alerts.GRACE_S


def test_timers_are_collected_from_the_top_level_and_the_areas():
    """The connector sends `timers` at the top level (for apps before 3.12.0) and inside `areas`; a
    collector reading only one of them misses every timer on one of the two paths."""
    payload = {"timers": [{"key": "a", "ends_at": 1}],
               "areas": [{"id": "timers", "timers": [{"key": "b", "ends_at": 2}]},
                         {"id": "location", "lines": ["x"]}]}
    assert [t["key"] for t in alerts.collect(payload)] == ["a", "b"]


def test_collect_survives_a_payload_without_timers():
    """The overlay payload is plugin data; a missing or oddly-shaped key must not raise inside the tray's
    poll loop."""
    assert alerts.collect({}) == []
    assert alerts.collect({"areas": [{"id": "x"}], "timers": None}) == []


def test_remaining_text_counts_down_and_then_says_done():
    """The overlay and the page both show this; a negative countdown reading `-00:05` is noise."""
    assert alerts.format_remaining({"ends_at": 1000}, now=400).endswith("10:00")
    assert "done" in alerts.format_remaining({"ends_at": 100}, now=200)
    assert alerts.format_remaining({"ends_at": 100000}, now=0).startswith("27 h")
