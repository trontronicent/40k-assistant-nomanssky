"""Fakes and helpers shared by the standalone host's route tests.

A fake plugin instead of the real connector: the routes are what is under test here, and the connector
has its own tests. `FakeBridge` runs the coroutine on the calling thread - the real one hands it to the
host's loop, which the runner tests cover.
"""
import asyncio

import pytest

from standalone import routes, server


class FakeBridge:
    """Stands in for `runner.LoopBridge`: runs the coroutine to completion and returns its value."""

    def call(self, coro, timeout):
        return asyncio.run(_wrap(coro))


async def _wrap(coro):
    return await coro


class FakePlugin:
    """The connector's host-facing surface, reduced to what the routes call."""

    def __init__(self):
        self.actions = []

    def view(self):
        return {"sections": [{"type": "text", "text": "hello"}]}

    async def action(self, action_id, params):
        self.actions.append((action_id, params))
        return {"message": "done", "focus": "system-map"}

    def item_icons(self):
        return {"Copper": "copper.png"}

    def overlay(self):
        return {"title": "No Man's Sky", "areas": []}

    def personas(self):
        return [{"slug": "companion", "name": "NMS Companion", "system_prompt": "You are the companion."}]

    def chat_context(self, question):
        return {"title": "No Man's Sky", "text": f"asked: {question}"}


def build_deps(tmp_path, plugin=None, **extra):
    """A `routes.Deps` pointing at temporary folders."""
    plugin = plugin or FakePlugin()
    deps = routes.Deps(plugin=plugin, bridge=FakeBridge(), assets_dir=tmp_path / "assets",
                       settings_path=tmp_path / "standalone.json", web_dir=tmp_path / "web",
                       version="0.15.0-beta.3", **extra)
    deps.assets_dir.mkdir(parents=True, exist_ok=True)
    deps.web_dir.mkdir(parents=True, exist_ok=True)
    return deps


@pytest.fixture
def api(tmp_path):
    """`(deps, plugin)` for a route test."""
    plugin = FakePlugin()
    return build_deps(tmp_path, plugin), plugin


def call(deps, method, path, body=None):
    """Dispatch one request through the real route table and return the `Response`."""
    for route in routes.build(deps):
        match = route.regex.match(path)
        if route.method == method and match:
            request = server.Request(method, path, {}, body or {}, match.groups(), {})
            try:
                return route.handler(request)
            except server.HttpError as err:
                return server.error_response(err.status, err.detail)
    raise AssertionError(f"no route for {method} {path}")
