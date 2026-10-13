"""The tray's pure menu model and its pystray glue contract."""
import inspect

from standalone import tray, tray_menu


def menu(**kwargs):
    options = {"overlay_on": True, "ai_enabled": True, "update": None}
    options.update(kwargs)
    return tray_menu.build_menu(**options)


def test_the_menu_offers_the_actions_the_program_needs():
    """The tray is the only UI the autostart entry shows, so everything the user must reach without a
    browser has to be in it."""
    locals_ = [entry.local for entry in menu() if entry.local]
    for name in ("open_page", "toggle_overlay", "open_data_folder", "open_log", "check_updates",
                 "rescan", "restart", "quit"):
        assert name in locals_, name


def test_the_first_entry_is_the_default_action():
    """A left click on a Windows tray icon runs the default item; without one, clicking the icon does
    nothing and the program looks dead."""
    entries = menu()
    assert entries[0].default is True and entries[0].local == "open_page"


def test_the_chat_entry_is_hidden_without_ai():
    """Offering a chat the install does not have produces a page tab that only says "not installed"."""
    assert not any(entry.local == "open_chat" for entry in menu(ai_enabled=False))
    assert any(entry.local == "open_chat" for entry in menu(ai_enabled=True))


def test_an_available_update_is_shown_in_the_menu():
    """The updater is the one thing a user will not look for; the tray says a version is waiting."""
    assert any("0.16.0" in entry.text for entry in menu(update="0.16.0"))


def test_the_overlay_entry_is_a_check_reflecting_the_state():
    """The overlay toggle must show whether the overlay is on, or the user cannot tell what a click
    will do."""
    entry = next(entry for entry in menu(overlay_on=True) if entry.local == "toggle_overlay")
    assert entry.kind == "check" and entry.checked is True
    entry = next(entry for entry in menu(overlay_on=False) if entry.local == "toggle_overlay")
    assert entry.checked is False


def test_the_menu_has_separators_but_never_two_in_a_row():
    """Win32 draws exactly what it is given; a double separator is a visible glitch."""
    kinds = [entry.kind for entry in menu()]
    assert "separator" in kinds
    assert not any(a == b == "separator" for a, b in zip(kinds, kinds[1:], strict=False))


def test_the_menu_text_is_cut_for_win32():
    """Win32 menus do not wrap; the app cuts at 48 characters and the tooltip at 120 (Windows truncates
    at 127). The same limits apply here."""
    assert len(tray_menu.cut("x" * 200)) <= tray_menu.MAX_TEXT
    assert len(tray_menu.tooltip("x" * 300, port=8787)) <= tray_menu.MAX_TOOLTIP


def test_the_tooltip_names_the_port():
    """Hovering the icon has to answer "where is it serving?" without opening anything."""
    assert "8787" in tray_menu.tooltip("ready", port=8787)


def test_every_callback_takes_the_two_parameters_pystray_passes():
    """pystray inspects a callback's arity and calls it with (icon, item). A handler with a different
    signature is silently never run - the trap the app's tray already hit."""
    handler = tray.make_handler(lambda: None)
    assert list(inspect.signature(handler).parameters) == ["icon", "item"]


def test_a_failing_menu_action_is_logged_not_raised(caplog):
    """An exception inside a pystray callback disappears into the Win32 message loop; it must be logged
    or a broken menu entry looks like a frozen tray."""
    def boom():
        raise RuntimeError("kaputt")

    tray.make_handler(boom)(None, None)
    assert "kaputt" in caplog.text


def test_the_watcher_notifies_through_the_shared_alert_rule():
    """This is what makes alerts work with no page open: the tray polls the host's overlay payload and
    announces the same timers the page would have."""
    shown = []
    watcher = tray.AlertWatcher(notify=lambda title, text: shown.append(title))
    payload = {"areas": [{"id": "timers", "timers": [{"key": "t1", "label": "Settlement",
                                                      "ends_at": 100}]}]}
    watcher.poll(payload, now=101)
    watcher.poll(payload, now=102)
    assert shown == ["Settlement"]


def test_the_watcher_says_nothing_while_a_timer_runs():
    """A balloon for a construction with two hours left would be noise."""
    shown = []
    watcher = tray.AlertWatcher(notify=lambda title, text: shown.append(title))
    watcher.poll({"timers": [{"key": "t", "label": "X", "ends_at": 10000}]}, now=0)
    assert shown == []


def test_a_failing_notification_does_not_stop_the_poll():
    """The balloon is optional; the tray must keep running if Windows refuses to show one."""
    def boom(title, text):
        raise RuntimeError("no balloons today")

    watcher = tray.AlertWatcher(notify=boom)
    watcher.poll({"timers": [{"key": "t", "label": "X", "ends_at": 100}]}, now=101)
