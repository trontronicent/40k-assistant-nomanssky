"""The overlay's pure layout and choice rules, and the recipe viewer's real widgets."""
import json

import pytest

from standalone import overlay


def test_areas_follow_the_users_choice_over_the_plugins_default():
    """The plugin says what is on by default; the user's switch wins afterwards, or every restart undoes
    what they turned off. The app stores the choice on its side for the same reason."""
    payload = {"areas": [{"id": "timers", "title": "Timers", "default_on": True, "lines": ["a"]},
                         {"id": "ships", "title": "Ships", "default_on": False, "lines": ["b"]}]}
    rows = overlay.visible_areas(payload, {"ships": True, "timers": False})
    assert [area["id"] for area in rows] == ["ships"]


def test_a_missing_choice_follows_the_plugins_default():
    """A newly added area must appear without the user having to find it first."""
    payload = {"areas": [{"id": "timers", "title": "Timers", "default_on": True},
                         {"id": "frigates", "title": "Frigates", "default_on": False}]}
    assert [area["id"] for area in overlay.visible_areas(payload, {})] == ["timers"]


def test_an_empty_area_is_still_listed():
    """An area with no data yet must appear, so it can be chosen before the game supplies anything - the
    app's rule, and the reason its normaliser keeps an empty area."""
    payload = {"areas": [{"id": "settlements", "title": "Settlements", "default_on": True, "lines": []}]}
    assert overlay.visible_areas(payload, {}) != []


def test_areas_without_an_id_or_a_title_are_dropped():
    """The payload is plugin data; an unusable entry must not become a blank row with no way to hide it."""
    payload = {"areas": [{"title": "No id"}, {"id": "ok", "title": "Fine"}, "nonsense"]}
    assert [area["id"] for area in overlay.visible_areas(payload, {})] == ["ok"]


def test_the_pre_area_payload_still_works():
    """A connector older than app 3.12.0 sends only `timers` and `lines`; the overlay must fall back to
    them instead of showing nothing."""
    payload = {"title": "No Man's Sky", "timers": [{"key": "t", "label": "X", "ends_at": 10}],
               "lines": ["You are on Ulebsk I"]}
    areas = overlay.visible_areas(payload, {})
    assert [area["id"] for area in areas] == [overlay.FALLBACK_AREA_ID]
    assert areas[0]["lines"] == ["You are on Ulebsk I"]


def test_area_rows_show_a_countdown_per_timer():
    """The overlay exists so the user sees a construction finish without leaving the game; the row must
    be a remaining time, not an end timestamp."""
    area = {"id": "timers", "title": "Timers", "timers": [{"key": "t", "label": "Settlement",
                                                           "ends_at": 1000}]}
    rows = overlay.area_rows(area, now=400)
    assert rows == ["Settlement  10:00"]


def test_a_finished_timer_says_so():
    """A negative countdown reading `-00:05` is noise; a finished timer says it is done until the plugin
    drops it."""
    area = {"id": "timers", "title": "T", "timers": [{"key": "t", "label": "X", "ends_at": 100}]}
    assert "done" in overlay.area_rows(area, now=200)[0]


def test_lines_are_bounded_and_cleaned():
    """Overlay lines are drawn over a game at a small size; the app bounds them to 12 of 160 characters
    and drops the invalid ones before the cap."""
    area = {"id": "x", "title": "X", "lines": ["ok", "", None, "y" * 400] + [f"l{i}" for i in range(20)]}
    rows = overlay.area_rows(area, now=0)
    assert len(rows) == overlay.MAX_AREA_LINES
    assert all(len(row) <= overlay.MAX_LINE_CHARS for row in rows)


def test_the_overlay_keeps_its_last_content_when_the_host_is_silent():
    """The host restarts during an update. The overlay must keep its last content and show a quiet note
    instead of dying, which would leave the user with no way back."""
    state = overlay.OverlayState()
    state.apply({"areas": [{"id": "a", "title": "A", "lines": ["x"], "default_on": True}]})
    state.failed("connection refused")
    assert state.stale is True
    assert state.payload["areas"][0]["lines"] == ["x"]
    assert "connection refused" in state.note


def test_a_recovered_poll_clears_the_stale_mark():
    """Once the host answers again the note must go, or the user keeps reading a warning about nothing."""
    state = overlay.OverlayState()
    state.failed("boom")
    state.apply({"areas": []})
    assert state.stale is False and state.note == ""


def test_choices_round_trip_through_the_file(tmp_path):
    """The user's on/off choice must survive a restart; it lives in the data dir, not in the plugin."""
    path = tmp_path / "overlay.json"
    overlay.save_choices(path, {"timers": True, "ships": False}, geometry="+100+200")
    loaded = overlay.load_choices(path)
    assert loaded["areas"] == {"timers": True, "ships": False}
    assert loaded["geometry"] == "+100+200"


def test_a_damaged_choices_file_reads_as_defaults(tmp_path):
    """A half-written file must not stop the overlay from opening."""
    (tmp_path / "overlay.json").write_text("{broken", encoding="utf-8")
    assert overlay.load_choices(tmp_path / "overlay.json") == {"areas": {}, "geometry": ""}


def test_the_poll_url_points_at_the_hosts_overlay_route(tmp_path):
    """The overlay is a second process; it reads exactly what the page reads, so there is one source of
    truth for what the connector wants shown."""
    assert overlay.overlay_url(8799) == "http://127.0.0.1:8799/api/overlay"


def test_the_geometry_is_remembered_as_the_user_dragged_it(tmp_path):
    """Dragging the overlay into a corner is a per-machine preference; losing it on every start would make
    the window useless over a full-screen game."""
    path = tmp_path / "overlay.json"
    overlay.save_choices(path, {}, geometry="+1200+40")
    assert json.loads(path.read_text(encoding="utf-8"))["geometry"] == "+1200+40"


def test_the_geometry_offset_is_read_from_a_tkinter_string():
    """The drag handler saves this on every release. Getting it wrong means the window forgets where the
    user dragged it - and the tkinter part itself is not covered by tests, so the rule lives here."""
    assert overlay.geometry_offset("240x120+1200+40") == "+1200+40"
    assert overlay.geometry_offset("+1200+40") == "+1200+40"
    assert overlay.geometry_offset("240x120") == ""
    assert overlay.geometry_offset("") == ""


def test_the_plugins_own_switches_become_menu_rows():
    """`toggles` are the plugin's settings (`single_context` today). The app's overlay draws them as rows
    that run the plugin's action; the standalone overlay puts them in its right-click menu, and the
    plugin - not the overlay - owns the value."""
    payload = {"toggles": [{"id": "single_context", "label": "Single context per question",
                            "value": False, "action": "set_setting", "hint": "Helps saving VRAM"}]}
    rows = overlay.toggle_rows(payload)
    assert rows == [{"id": "single_context", "label": "Single context per question", "value": False,
                     "hint": "Helps saving VRAM", "action": "set_setting"}]


def test_a_toggle_without_an_action_is_dropped():
    """Without an action there is nothing a click could do; a dead row is worse than no row."""
    assert overlay.toggle_rows({"toggles": [{"id": "x", "label": "X"}, "nonsense"]}) == []


def test_toggles_are_bounded():
    """The app allows at most four; more would push the areas off a small overlay."""
    many = [{"id": f"t{i}", "label": "T", "action": "set_setting"} for i in range(10)]
    assert len(overlay.toggle_rows({"toggles": many})) == overlay.MAX_TOGGLES


def test_the_codex_search_opt_in_is_noticed():
    """The connector sets `codex_search: true` to ask for a search in its persona's library. The overlay
    offers the page's Codex tab, which is where that search lives in the standalone host."""
    assert overlay.wants_codex_search({"codex_search": True}) is True
    assert overlay.wants_codex_search({"codex_search": "yes"}) is False
    assert overlay.wants_codex_search({}) is False


# --- the recipe viewer in the overlay --------------------------------------------------------------

RECIPE = {"ingredients": [{"amount": 1, "name": "Nitrogen", "icon": "gas.1.png"},
                          {"amount": 1, "name": "Di-hydrogen"}],
          "result": {"amount": 1, "name": "Ammonia", "icon": "toxic.png"},
          "station": "Medium Refiner or larger"}
RECIPE_PAYLOAD = {"recipe_search": "search_recipes", "areas": [
    {"id": "location", "title": "Where you are", "lines": ["Delta Sol"], "default_on": True},
    {"id": "recipes", "title": "Recipes", "default_on": True, "search": True, "query": "ammonia",
     "recipes": [RECIPE], "lines": ["1 Nitrogen + 1 Di-hydrogen -> 1 Ammonia"]}]}


def test_the_recipe_area_is_recognised_and_its_action_checked():
    """The viewer's area is the one with diagrams or its own box; the action its box runs is checked like
    any action id, because it becomes a URL path on the host."""
    assert [a["id"] for a in overlay.recipe_areas(RECIPE_PAYLOAD, {})] == ["recipes"]
    assert overlay.recipe_areas(RECIPE_PAYLOAD, {"recipes": False}) == []
    assert overlay.search_action(RECIPE_PAYLOAD) == "search_recipes"
    assert overlay.search_action({"recipe_search": "../escape"}) == ""
    assert overlay.search_action({}) == ""


def test_a_recipe_becomes_cards_with_the_marks_between_them():
    """The drawing is only placement, so the cards are decided here: amount and name per item, "+" between
    the ingredients, the arrow before the result, and the icon file each card carries."""
    assert overlay.recipe_cards(RECIPE) == [
        ("1 Nitrogen", "gas.1.png"), ("+", ""), ("1 Di-hydrogen", ""), ("→", ""), ("1 Ammonia", "toxic.png")]


def test_a_half_read_recipe_yields_no_cards_at_all():
    """An arrow pointing at nothing would look like a bug in the game data; such an entry is skipped."""
    assert overlay.recipe_cards({"ingredients": [{"amount": 1, "name": "A"}]}) == []
    assert overlay.recipe_cards({"result": {"amount": 1, "name": "B"}}) == []
    assert overlay.recipe_cards({}) == []


_TK = {}


def _window(tmp_path, payload, port=1):
    """A real overlay window with a payload already applied, as a Toplevel under one hidden root shared by
    these tests (several `Tk()` roots in one process intermittently fail with "Can't find a usable tk.tcl",
    the same trap the app's overlay tests hit); skipped where there is no display at all."""
    tk = pytest.importorskip("tkinter")
    if "root" not in _TK:
        try:
            _TK["root"] = tk.Tk()
        except tk.TclError as err:
            pytest.skip(f"no display: {err}")
        _TK["root"].withdraw()
    window = overlay.OverlayWindow(port, tmp_path, root=tk.Toplevel(_TK["root"]))
    window.state.apply(payload)
    return window


def _labels(widget, out=None):
    """Every label text below `widget`, in drawing order."""
    out = [] if out is None else out
    for child in widget.winfo_children():
        if child.winfo_class() == "Label":
            out.append(child.cget("text"))
        _labels(child, out)
    return out


def test_the_window_draws_the_recipe_diagrams_and_searches_through_the_host(tmp_path):
    """The real window: the recipe area gets a text box and one row of cards per recipe (with the marks and
    the station), its text block no longer repeats them, and Enter posts the connector's action with the
    words typed - the connector then answers the next poll, so the overlay and the page agree."""
    window = _window(tmp_path, RECIPE_PAYLOAD)
    posted = []
    window._post_action = lambda action, params: posted.append((action, params)) or ""
    window.poll_now = lambda: None
    try:
        window.render()
        window.root.update()
        assert window._query_box is not None
        texts = _labels(window.recipes)
        assert "1 Nitrogen" in texts and "1 Ammonia" in texts and "→" in texts and "+" in texts
        assert "Medium Refiner or larger" in texts
        # The area is drawn as diagrams, so the text block holds only the other area.
        assert "Recipes" not in window.body.cget("text") and "Delta Sol" in window.body.cget("text")
        window._query_box.insert(0, "  ferrit  staub ")
        window._query_box.focus_force()          # a borderless window does not hold the keyboard by itself
        window.root.update()
        window._query_box.event_generate("<Return>")
        window.root.update()
        assert posted == [("search_recipes", {"query": "ferrit staub"})]
        window.clear_search()
        assert window._query_box.get() == "" and posted[-1] == ("search_recipes", {"query": ""})
    finally:
        window.root.destroy()


def test_an_area_without_diagrams_still_shows_its_lines(tmp_path):
    """"Nothing matches" must be readable: with no diagram to draw, the area's `lines` are shown as text -
    the same fallback an overlay from before the viewer relied on."""
    payload = {"recipe_search": "search_recipes", "areas": [
        {"id": "recipes", "title": "Recipes", "search": True, "recipes": [], "lines": ['Nothing matches "zzz".'],
         "default_on": True}]}
    window = _window(tmp_path, payload)
    try:
        window.render()
        window.root.update()
        assert 'Nothing matches "zzz".' in window.body.cget("text")
        assert not [w for w in window.recipes.winfo_children() if w.winfo_class() == "Frame"]
    finally:
        window.root.destroy()


def test_an_icon_is_read_from_the_plugins_assets_and_never_from_outside(tmp_path):
    """The icons are the plugin's own files next to the overlay, so there is nothing to download; a name
    that is not a plain file name is refused before it becomes a path, and a missing or damaged file costs
    the picture only - the card still shows the item."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "broken.png").write_bytes(b"not a png")
    window = _window(tmp_path, RECIPE_PAYLOAD)
    try:
        assert window._icon("../../secret.png") is None
        assert window._icon("missing.png") is None
        assert window._icon("broken.png") is None
        assert window._icon("") is None
    finally:
        window.root.destroy()
