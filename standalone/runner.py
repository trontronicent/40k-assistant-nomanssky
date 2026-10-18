"""Owns the asyncio loop and the plugin's life cycle, and lets the HTTP threads call into it."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from collections.abc import Callable, Coroutine

log = logging.getLogger("nms-standalone.runner")

START_TIMEOUT_S = 30.0
STOP_TIMEOUT_S = 15.0


class LoopBridge:
    """Call a coroutine on the host's loop from a server thread and wait for its answer.

    Every call into the connector goes through here, synchronous methods included: the connector's 5 s
    tick mutates the same state, and reading it from an HTTP thread is a torn read, not a crash.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    def call(self, coro: Coroutine[Any, Any, Any], timeout: float):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout)
        except TimeoutError:
            future.cancel()
            raise


async def on_loop(fn, *args):
    """Run one of the connector's synchronous methods on the host's loop (used with `LoopBridge.call`)."""
    return fn(*args)


def default_factory(ctx):
    """Import the connector from the install folder and build it (the entry the manifest names)."""
    from nms_connector import create_plugin
    return create_plugin(ctx)


class Runner:
    """Builds the context, starts the connector, hands it out, stops it."""

    def __init__(self, root: Path, data_dir: Path, codex=None,
                 factory: Callable[[Any], Any] = default_factory, version: str = ""):
        from standalone.context import StandaloneContext
        self.ctx = StandaloneContext("nomanssky", version, root, data_dir, codex=codex)
        self.plugin = factory(self.ctx)
        self.started = False

    async def start(self) -> None:
        await asyncio.wait_for(self.plugin.start(), START_TIMEOUT_S)
        self.started = True

    async def stop(self) -> None:
        """Stop the connector, then cancel its tasks. A failing `stop()` is logged, never raised: the
        process must exit either way."""
        try:
            await asyncio.wait_for(self.plugin.stop(), STOP_TIMEOUT_S)
        except (TimeoutError, Exception):      # noqa: B014 - logged; the exit must proceed
            log.warning("the connector's stop() failed; continuing shutdown", exc_info=True)
        finally:
            self.started = False
            await self.ctx.cancel_tasks()
