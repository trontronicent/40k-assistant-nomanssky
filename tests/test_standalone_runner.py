"""The standalone context and runner: the connector must see the same context the app gives it."""
import asyncio

from standalone import context, runner


def test_context_has_every_attribute_the_app_provides(tmp_path):
    """`nms_connector` reads these names off the context. A missing one is an AttributeError deep inside a
    5 s tick, so the contract is asserted here once instead of being discovered live."""
    ctx = context.StandaloneContext("nomanssky", "0.15.0", tmp_path, tmp_path / "data")
    for name in ("plugin_id", "version", "root", "data_dir", "assets_dir", "logger",
                 "app_version", "section_types", "codex", "spawn", "run_blocking"):
        assert hasattr(ctx, name), name


def test_context_reports_every_section_type(tmp_path):
    """The connector falls back to a plain table when `section_types` lacks e.g. `timers`. The standalone
    page renders all of them, so all of them must be advertised or the UI silently loses features."""
    ctx = context.StandaloneContext("nomanssky", "0.15.0", tmp_path, tmp_path / "data")
    assert {"timers", "tabs", "form", "orbit", "starmap"} <= set(ctx.section_types)


def test_context_creates_the_assets_dir(tmp_path):
    """The connector writes icon PNGs into `assets_dir` without creating it (the app's loader does).
    Without this the first icon write raises and every inventory table loses its pictures."""
    ctx = context.StandaloneContext("nomanssky", "0.15.0", tmp_path, tmp_path / "data")
    assert ctx.assets_dir.is_dir()


def test_spawned_tasks_are_cancelled_on_stop(tmp_path):
    """`ctx.spawn` must behave like the app's: tasks are held (never garbage-collected mid-run) and
    cancelled when the host stops, or the connector's loops outlive a shutdown."""
    async def scenario():
        ctx = context.StandaloneContext("nomanssky", "0.15.0", tmp_path, tmp_path / "data")
        started = asyncio.Event()

        async def loop():
            started.set()
            await asyncio.sleep(3600)

        task = ctx.spawn(loop(), "tick")
        await started.wait()
        await ctx.cancel_tasks()
        return task

    assert asyncio.run(scenario()).cancelled()


def test_a_crashed_background_task_is_logged(tmp_path, caplog):
    """An exception inside a spawned task must not vanish: the app's `spawn_background` logs it at ERROR
    with its traceback, and a silent death is this project's recurring bug class."""
    async def scenario():
        ctx = context.StandaloneContext("nomanssky", "0.15.0", tmp_path, tmp_path / "data")

        async def boom():
            raise RuntimeError("kaputt")

        task = ctx.spawn(boom(), "boom")
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    asyncio.run(scenario())
    assert "kaputt" in caplog.text


def test_runner_starts_and_stops_a_fake_plugin(tmp_path):
    """The runner owns the plugin's life cycle. A failed `stop()` must still let the host exit, because the
    connector releases memory in `stop()` and a hang there would leave the process alive."""
    calls = []

    class FakePlugin:
        def __init__(self, ctx):
            self.ctx = ctx

        async def start(self):
            calls.append("start")

        async def stop(self):
            calls.append("stop")
            raise RuntimeError("release failed")

        def view(self):
            return {"sections": []}

    async def scenario():
        run = runner.Runner(tmp_path, tmp_path / "data", factory=FakePlugin)
        await run.start()
        assert calls == ["start"]
        await run.stop()

    asyncio.run(scenario())
    assert calls == ["start", "stop"]


def test_bridge_calls_into_the_loop_from_a_thread(tmp_path):
    """The HTTP server runs in its own threads; every call into the plugin goes through the bridge. A
    bridge that ran the coroutine on the calling thread would corrupt the connector's state."""
    async def scenario():
        async def answer():
            return 42

        bridge = runner.LoopBridge(asyncio.get_running_loop())
        return await asyncio.to_thread(bridge.call, answer(), 5.0)

    assert asyncio.run(scenario()) == 42


def test_the_bridge_runs_the_call_on_the_hosts_loop(tmp_path):
    """Not just "it returns a value": the work must happen on the loop thread, which is the whole point -
    the connector's state is only safe there."""
    async def scenario():
        loop = asyncio.get_running_loop()
        seen = {}

        async def answer():
            seen["thread"] = __import__("threading").get_ident()
            return True

        bridge = runner.LoopBridge(loop)
        await asyncio.to_thread(bridge.call, answer(), 5.0)
        seen["loop_thread"] = __import__("threading").get_ident()
        return seen

    seen = asyncio.run(scenario())
    assert seen["thread"] == seen["loop_thread"]
