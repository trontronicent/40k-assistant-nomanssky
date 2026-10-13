"""The overlay's pure layout and choice rules (no window is created in the tests)."""
import json

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
