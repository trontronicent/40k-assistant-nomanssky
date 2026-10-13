"""The entry point's pure parts: argument parsing, port choice, logging setup, manifest version."""
import json
import logging

from standalone import __main__ as entry


def test_version_comes_from_the_manifest(tmp_path):
    """The page's header and the updater both show the installed version; reading it from
    `strategicum-plugin.json` keeps one source of truth with the plugin release recipe."""
    (tmp_path / "strategicum-plugin.json").write_text(json.dumps({"version": "0.15.0-beta.3"}),
                                                      encoding="utf-8")
    assert entry.installed_version(tmp_path) == "0.15.0-beta.3"


def test_a_missing_manifest_does_not_stop_the_host(tmp_path):
    """A half-finished update could leave the manifest missing; the host must still start so the user can
    reach the Updates page and reinstall."""
    assert entry.installed_version(tmp_path) == "unknown"


def test_free_port_prefers_the_configured_one(monkeypatch):
    """The user's bookmark and the overlay both point at the configured port, so it is only abandoned
    when something else holds it."""
    monkeypatch.setattr(entry, "port_is_free", lambda port: True)
    assert entry.choose_port(8787) == 8787


def test_an_occupied_port_falls_forward(monkeypatch):
    """A second instance (or any program on 8787) must not stop the host; it takes the next free port and
    the page is opened on that one."""
    monkeypatch.setattr(entry, "port_is_free", lambda port: port > 8788)
    assert entry.choose_port(8787) == 8789


def test_the_port_probe_has_a_short_timeout():
    """A connect to a closed localhost port takes ~2 s on Windows (it retries the SYN), so probing
    twenty ports with the default timeout would delay every start by most of a minute."""
    assert entry.PORT_PROBE_TIMEOUT_S <= 0.5


def test_logging_writes_to_the_data_dir(tmp_path):
    """Logs must not land in the install folder, which an update replaces, and never through a
    `Start-Process` redirect - two writers to one file lost 39 % of the lines on this machine."""
    entry.setup_logging(tmp_path / "standalone.log")
    logging.getLogger("nms-standalone").warning("hello")
    logging.getLogger().handlers[0].flush()
    assert "hello" in (tmp_path / "standalone.log").read_text(encoding="utf-8")


def test_args_can_turn_the_browser_overlay_and_tray_off():
    """The autostart entry starts the host without opening a browser window; the tests and a headless
    machine need the same switches."""
    args = entry.parse_args(["--no-browser", "--no-overlay", "--no-tray", "--port", "9001"])
    assert (args.no_browser, args.no_overlay, args.no_tray, args.port) == (True, True, True, 9001)


def test_deps_are_built_from_the_settings(tmp_path):
    """`Deps` is what every route reads. Without AI there must be no chat service at all, so the status
    route reports it off and the chat route refuses instead of failing on a missing model."""
    from standalone import config

    class FakeRunner:
        def __init__(self):
            self.ctx = type("Ctx", (), {"assets_dir": tmp_path / "assets"})()
            self.plugin = object()

    config.save(tmp_path / "standalone.json", config.Settings(ai_enabled=False))
    deps = entry.build_deps(FakeRunner(), tmp_path, tmp_path, "0.15.0-beta.3", None)
    assert deps.chat is None and deps.version == "0.15.0-beta.3"


def test_deps_get_a_chat_service_when_ai_is_on(tmp_path):
    """With AI configured the chat service must exist and carry the chosen model, or the page shows a
    chat box that answers 503."""
    from standalone import config

    class FakeRunner:
        def __init__(self):
            self.ctx = type("Ctx", (), {"assets_dir": tmp_path / "assets"})()
            self.plugin = type("P", (), {"personas": lambda self: [], "chat_context": lambda self, q: {}})()

    config.save(tmp_path / "standalone.json",
                config.Settings(ai_enabled=True, chat_model="40k-12b-companion"))
    deps = entry.build_deps(FakeRunner(), tmp_path, tmp_path, "0.15.0-beta.3", None)
    assert deps.chat is not None and deps.chat.model == "40k-12b-companion"
