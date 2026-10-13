"""The routes that serve the plugin's own data."""
import json

from standalone_fixtures import api, call  # noqa: F401 - `api` is a fixture used by name


def test_view_route_returns_the_plugins_view(api):  # noqa: F811
    """The page polls this every 5 s; it must pass the connector's sections through untouched - the
    standalone host does not normalise them, because it runs the same codebase, not a foreign plugin."""
    deps, _ = api
    body = json.loads(call(deps, "GET", "/api/view").body)
    assert body["sections"][0]["text"] == "hello"


def test_action_route_passes_params_and_returns_the_result(api):  # noqa: F811
    """Row clicks and form submits run actions; the `focus` key must survive, since the page uses it to
    select the tab the action pointed at."""
    deps, plugin = api
    body = json.loads(call(deps, "POST", "/api/actions/open_system", {"params": {"key": "7b"}}).body)
    assert plugin.actions == [("open_system", {"key": "7b"})]
    assert body["focus"] == "system-map"


def test_action_params_are_bounded(api):  # noqa: F811
    """Params are untrusted input (the page is local, but a browser tab is not a trusted caller): too
    many keys, nested values or oversized text are refused with 422 before the plugin runs."""
    deps, plugin = api
    too_many = {f"k{i}": 1 for i in range(60)}
    assert call(deps, "POST", "/api/actions/rescan", {"params": too_many}).status == 422
    assert call(deps, "POST", "/api/actions/rescan", {"params": {"a": {"b": 1}}}).status == 422
    assert call(deps, "POST", "/api/actions/rescan", {"params": {"a": "x" * 3000}}).status == 422
    assert plugin.actions == []


def test_unknown_action_id_is_refused_before_the_plugin(api):  # noqa: F811
    """An action id must match the app's `ACTION_ID_RE`; anything else is refused, so a mistyped fetch
    from the page cannot reach `action()` with junk."""
    deps, plugin = api
    assert call(deps, "POST", "/api/actions/Rescan!", {}).status == 422
    assert plugin.actions == []


def test_asset_route_serves_a_png_from_the_assets_dir(api):  # noqa: F811
    """Inventory tables show icon cells; the page fetches them from here. The name must match the app's
    `ICON_NAME_RE` and resolve directly inside `assets_dir`."""
    deps, _ = api
    (deps.assets_dir / "copper.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    response = call(deps, "GET", "/api/assets/copper.png")
    assert response.status == 200
    assert response.content_type == "image/png"


def test_asset_route_refuses_a_traversal(api):  # noqa: F811
    """A path like `..%2Fstandalone.json` must not escape the assets folder; the resolved path is
    compared against it, as the app's `manager.asset_path` does."""
    deps, _ = api
    assert call(deps, "GET", "/api/assets/..%2Fstandalone.json").status == 404


def test_item_icons_route(api):  # noqa: F811
    """The chat renders recipe lines as pictures by resolving item names against this map, fetched once
    per page load."""
    deps, _ = api
    assert json.loads(call(deps, "GET", "/api/item-icons").body)["icons"]["Copper"] == "copper.png"


def test_overlay_route(api):  # noqa: F811
    """The overlay window and the tray both poll this; it is the connector's own `overlay()` payload."""
    deps, _ = api
    assert json.loads(call(deps, "GET", "/api/overlay").body)["title"] == "No Man's Sky"


def test_status_route_names_the_version_and_the_features(api):  # noqa: F811
    """The page's header shows the installed version and hides the chat when AI is off, so status is the
    one call it makes before anything else."""
    deps, _ = api
    body = json.loads(call(deps, "GET", "/api/status").body)
    assert body["version"] == "0.15.0-beta.3"
    assert body["ai_enabled"] is False


def test_the_web_route_serves_the_page(api):  # noqa: F811
    """`/` is the page itself; only files directly inside `web/` and only known extensions."""
    deps, _ = api
    (deps.web_dir / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
    response = call(deps, "GET", "/")
    assert response.status == 200 and response.content_type.startswith("text/html")


def test_the_web_route_refuses_an_unknown_extension(api):  # noqa: F811
    """A file the page never asks for (a `.py`, a `.json` of settings) must not be served just because it
    sits in the folder."""
    deps, _ = api
    (deps.web_dir / "secret.py").write_text("x = 1", encoding="utf-8")
    assert call(deps, "GET", "/secret.py").status == 404
