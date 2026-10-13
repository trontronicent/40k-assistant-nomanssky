"""The settings route: what the page may change, and what it may not."""
import json

from standalone import config
from standalone_fixtures import api, build_deps, call  # noqa: F401 - `api` is used as a fixture


def test_the_model_can_be_changed(api):  # noqa: F811
    """The installer pulls one model, but the user may have others; picking one must persist, because the
    chat is unusable with a model that is not installed."""
    deps, _ = api
    response = call(deps, "PUT", "/api/settings", {"chat_model": "40k-12b-companion"})
    assert response.status == 200
    assert config.load(deps.settings_path).chat_model == "40k-12b-companion"


def test_unknown_keys_are_refused(api):  # noqa: F811
    """The settings file is read on every start; an arbitrary key would be dropped by `config.load` and
    look to the user as if the save had failed."""
    deps, _ = api
    assert call(deps, "PUT", "/api/settings", {"nonsense": 1}).status == 422


def test_types_are_checked(api):  # noqa: F811
    """A port as a string or a flag as a number must not reach the file; the next start would fall back
    to the defaults and the user would lose their choices."""
    deps, _ = api
    assert call(deps, "PUT", "/api/settings", {"port": "8787"}).status == 422
    assert call(deps, "PUT", "/api/settings", {"ai_enabled": 1}).status == 422


def test_the_port_is_bounded(api):  # noqa: F811
    """A port outside 1024..65535 makes the next start fail before it can serve the page that would fix
    it, so it is refused here."""
    deps, _ = api
    assert call(deps, "PUT", "/api/settings", {"port": 80}).status == 422
    assert call(deps, "PUT", "/api/settings", {"port": 70000}).status == 422
    assert call(deps, "PUT", "/api/settings", {"port": 8790}).status == 200


def test_the_channel_must_be_one_of_the_two(api):  # noqa: F811
    """An unknown channel would silently behave like stable and hide the beta line this plugin ships on."""
    deps, _ = api
    assert call(deps, "PUT", "/api/settings", {"update_channel": "nightly"}).status == 422
    assert call(deps, "PUT", "/api/settings", {"update_channel": "pre-release"}).status == 200


def test_ai_cannot_be_turned_on_without_a_reachable_ollama(api):  # noqa: F811
    """Turning AI on with nothing behind it produces a chat box that fails on every message; the route
    probes first and answers why."""
    deps, _ = api
    response = call(deps, "PUT", "/api/settings", {"ai_enabled": True})
    assert response.status == 409 and "Ollama" in json.loads(response.body)["detail"]


def test_ai_can_be_turned_on_when_ollama_answers(tmp_path):
    """The positive case: with a server and a model the switch must take."""
    class FakeProbe:
        def available(self):
            return True

        def tags(self):
            return ["40k-12b-companion:latest"]

    deps = build_deps(tmp_path, probe=FakeProbe())
    assert call(deps, "PUT", "/api/settings", {"ai_enabled": True}).status == 200
    assert config.load(deps.settings_path).ai_enabled is True


def test_turning_ai_off_needs_no_probe(api):  # noqa: F811
    """Switching a feature off must always work, even when the thing behind it is already gone."""
    deps, _ = api
    config.save(deps.settings_path, config.Settings(ai_enabled=True))
    assert call(deps, "PUT", "/api/settings", {"ai_enabled": False}).status == 200


def test_a_restart_is_announced_for_what_needs_one(api):  # noqa: F811
    """Model and voice take effect on the next turn; the port, the overlay and the Codex need a restart.
    Saying so is the difference between "it did nothing" and "it will apply"."""
    deps, _ = api
    body = json.loads(call(deps, "PUT", "/api/settings", {"port": 8791}).body)
    assert body["restart_needed"] is True
    body = json.loads(call(deps, "PUT", "/api/settings", {"chat_model": "x"}).body)
    assert body["restart_needed"] is False


def test_the_models_route_lists_what_ollama_has(api):  # noqa: F811
    """The picker needs the installed models; without AI it answers an empty list rather than failing, so
    the page can say "install the AI assistant"."""
    deps, _ = api
    assert json.loads(call(deps, "GET", "/api/models").body)["models"] == []


def test_the_models_route_reports_the_shipped_model(tmp_path):
    """The installer creates `40k-12b-companion`; `ollama list` shows it as `:latest`, and the page must
    still recognise it as present."""
    class FakeProbe:
        def available(self):
            return True

        def tags(self):
            return ["40k-12b-companion:latest", "nomic-embed-text:latest"]

    deps = build_deps(tmp_path, probe=FakeProbe())
    body = json.loads(call(deps, "GET", "/api/models").body)
    assert "40k-12b-companion:latest" in body["models"] and body["available"] is True
