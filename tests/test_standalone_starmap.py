"""The system map and galaxy map geometry, under Node."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "standalone" / "web"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH")


def run_js(script: str):
    source = f"const M = require({json.dumps(str(WEB / 'starmap.js'))});\n{script}"
    out = subprocess.run([NODE, "-e", source], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_orbit_places_bodies_on_growing_orbits():
    """The system map is the plugin's main picture; bodies must not land on top of each other, which is
    what a constant orbit radius does with six planets."""
    bodies = [{"label": f"P{i}"} for i in range(6)]
    xs = run_js(f"console.log(JSON.stringify(M.orbitLayout({{center:{{label:'S'}},bodies:{json.dumps(bodies)}}})"
                ".bodies.map(b => b.cx)));")
    assert xs == sorted(xs) and len(set(xs)) == 6


def test_orbit_alternates_above_and_below():
    """Alternating sides keeps labels readable; all bodies on one line overlap their text."""
    bodies = [{"label": "a"}, {"label": "b"}, {"label": "c"}, {"label": "d"}]
    signs = run_js(f"const l = M.orbitLayout({{center:{{label:'S'}},bodies:{json.dumps(bodies)}}});"
                   "console.log(JSON.stringify(l.bodies.map(b => Math.sign(b.cy - l.height / 2))));")
    assert signs == [-1, 1, -1, 1]


def test_orbit_is_capped_at_the_apps_limit():
    """The app's `views._orbit` allows at most 24 bodies; drawing more would silently disagree with what
    the connector was told it may send."""
    bodies = [{"label": f"P{i}"} for i in range(40)]
    count = run_js(f"console.log(JSON.stringify(M.orbitLayout({{center:{{}},bodies:{json.dumps(bodies)}}})"
                   ".bodies.length));")
    assert count == 24


def test_body_colour_falls_back_when_the_plugin_sends_junk():
    """`color` comes from plugin data; anything but `#rrggbb` must fall back instead of reaching an SVG
    attribute, matching the app's `COLOR_RE`."""
    assert run_js("console.log(JSON.stringify(M.bodyColor('#aabbcc')))") == "#aabbcc"
    assert run_js("console.log(JSON.stringify([M.bodyColor('red; url(x)') === M.DEFAULT_BODY_COLOR,"
                  "M.bodyColor(undefined) === M.DEFAULT_BODY_COLOR]))") == [True, True]


def test_body_size_is_clamped():
    """Size is a plugin number; the app clamps it to 0.3-3 so one bad value cannot cover the whole map."""
    assert run_js("console.log(JSON.stringify([M.clampSize(99), M.clampSize(0.01), M.clampSize('x')]))") \
        == [3, 0.3, 1]


def test_starmap_fit_contains_every_point():
    """The galaxy tab opens on up to 3,000 points; a view that does not contain them opens on empty
    space."""
    points = [{"x": -10, "y": 0, "z": 5}, {"x": 40, "y": 0, "z": -30}]
    view = run_js(f"console.log(JSON.stringify(M.starmapFit({json.dumps(points)}, 'top')));")
    assert view["w"] >= 50 and view["h"] >= 35


def test_starmap_fit_of_one_point_is_still_a_usable_view():
    """A single recorded system must not produce a zero-sized viewBox (which renders nothing at all)."""
    view = run_js("console.log(JSON.stringify(M.starmapFit([{x:1,y:1,z:1}], 'top')));")
    assert view["w"] >= 10 and view["h"] >= 10


def test_starmap_zoom_keeps_the_cursor_fixed():
    """The wheel zooms around the cursor; a zoom that moves the point under the cursor makes the map
    impossible to aim, which is why the app computes it this way."""
    result = run_js("const v={cx:0,cy:0,w:100,h:100};"
                    "const z=M.starmapZoom(v,{x:25,y:25},0.5);"
                    "console.log(JSON.stringify(M.starmapProject(z,{x:25,y:0,z:25},'top')));")
    assert abs(result["sx"] - 0.75) < 0.01


def test_side_view_flips_y():
    """Top view is x/z, side view x/-y (the app's convention). Without the flip the galaxy is upside
    down and the *You* button points at the wrong half."""
    assert run_js("console.log(JSON.stringify(M.axes('side')))") == ["x", "y", -1]
    assert run_js("console.log(JSON.stringify(M.axes('top')))") == ["x", "z", 1]


def test_grid_step_stays_readable():
    """A grid of 1/2/5 x 10^n keeps about six lines at any zoom; a fixed step is either invisible or a
    solid block."""
    steps = run_js("console.log(JSON.stringify([M.starmapGridStep(60), M.starmapGridStep(6000),"
                   "M.starmapGridStep(0.6)]));")
    assert steps == [10, 1000, 0.1]


def test_find_matches_label_and_sublabel_prefix_first():
    """The galaxy tab has a search field; names starting with the query must come first, as in the app's
    `pluginModel.starmapFind`."""
    points = [{"key": "a", "label": "Ulebsk", "sublabel": "Technology"},
              {"key": "b", "label": "Agestr", "sublabel": "Ulebsk belt"}]
    hits = run_js(f"console.log(JSON.stringify(M.starmapFind({json.dumps(points)}, 'uleb').map(p => p.key)));")
    assert hits == ["a", "b"]


def test_the_renderer_draws_an_orbit_through_this_module():
    """`sections.js` delegates `orbit`/`starmap` to this module, so the two must agree on what the
    builder receives - a helper missing from the render api is a crash on the real page, which the
    geometry tests alone would not catch."""
    sections = Path(__file__).resolve().parent.parent / "standalone" / "web" / "sections.js"
    view = {"sections": [{"type": "orbit", "title": "System", "center": {"label": "Ulebsk"},
                          "bodies": [{"label": "Ulebsk I", "items": [{"label": "Biome", "value": "Lush"}]}]},
                         {"type": "starmap", "title": "Galaxy",
                          "points": [{"key": "a", "label": "Ulebsk", "x": 0, "y": 0, "z": 0}]}]}
    source = (f"const S = require({json.dumps(str(sections))});"
              f"const M = require({json.dumps(str(WEB / 'starmap.js'))});"
              f"const r = S.renderSections({json.dumps(view)}, "
              "{orbit: M.orbit, starmap: M.starmap, el: S.el, appendCell: S.appendCell});"
              "console.log(JSON.stringify({types: r.types, html: r.html.length > 100}));")
    out = subprocess.run([NODE, "-e", source], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout)
    assert result["types"] == ["orbit", "starmap"] and result["html"] is True


def test_the_default_render_api_already_carries_the_drawing_helpers():
    """`app.js` must not have to remember to pass `el`/`appendCell`; the renderer supplies its own
    helpers, so a page that only overrides `orbit`/`starmap` still works."""
    sections = Path(__file__).resolve().parent.parent / "standalone" / "web" / "sections.js"
    source = (f"const S = require({json.dumps(str(sections))});"
              f"const M = require({json.dumps(str(WEB / 'starmap.js'))});"
              "const view = {sections: [{type: 'orbit', center: {label: 'S'}, bodies: [{label: 'P'}]}]};"
              "const r = S.renderSections(view, {orbit: M.orbit, starmap: M.starmap});"
              "console.log(JSON.stringify(r.types));")
    out = subprocess.run([NODE, "-e", source], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == ["orbit"]
