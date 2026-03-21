import asyncio
import textwrap
from sandy.daemon import Daemon


def _make_plugins(tmp_path, subdir, plugins):
    d = tmp_path / subdir
    d.mkdir(exist_ok=True)
    for filename, code in plugins.items():
        (d / filename).write_text(textwrap.dedent(code))
    return str(d)


def test_daemon_routes_message(tmp_path):
    """A message through the daemon reaches a content plugin and gets a response."""
    plugin_dir = _make_plugins(
        tmp_path,
        "plugins",
        {
            "echo.py": """
            name = "echo"
            commands = ["echo"]
            def handle(text, actor):
                return {"text": f"echo: {text}"}
        """
        },
    )

    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        results, errors = await daemon.handle_message("echo hello", "tom")
        assert len(results) == 1
        assert results[0][0] == "echo"
        assert results[0][1]["text"] == "echo: echo hello"

    asyncio.run(run())


def test_daemon_no_match(tmp_path):
    """A message with no matching plugin returns empty results."""
    plugin_dir = _make_plugins(
        tmp_path,
        "plugins",
        {
            "echo.py": """
            name = "echo"
            commands = ["echo"]
            def handle(text, actor):
                return {"text": "ok"}
        """
        },
    )

    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        results, errors = await daemon.handle_message("unknown", "tom")
        assert results == []

    asyncio.run(run())


def test_callback_no_match_sends_fallback(tmp_path):
    """Daemon callback sends fallback reply when no plugins match."""
    plugin_dir = _make_plugins(
        tmp_path,
        "plugins",
        {
            "echo.py": """
            name = "echo"
            commands = ["echo"]
            def handle(text, actor):
                return {"text": "ok"}
        """
        },
    )
    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        replies = []

        async def reply_fn(name, resp):
            replies.append((name, resp))

        # Build the callback the same way run() does and call it directly
        loop = asyncio.get_running_loop()
        progress_queue = asyncio.Queue()

        def make_progress(plugin_name):
            from sandy.progress import QueueProgressReporter

            return QueueProgressReporter(plugin_name, progress_queue, loop)

        async def drain():
            while True:
                msg = await progress_queue.get()
                if msg is None:
                    break
                await reply_fn("progress", {"text": msg})

        drain_task = asyncio.create_task(drain())
        try:
            results, errors = await daemon.handle_message(
                "unknown", "tom", progress_factory=make_progress
            )
        finally:
            await progress_queue.put(None)
            await drain_task

        for plugin_name, response in results:
            await reply_fn(plugin_name, response)
        for error in errors:
            await reply_fn("error", {"text": error})
        if not results and not errors:
            await reply_fn("sandy", {"text": "Sorry, I'm not sure how to do that."})

        assert replies == [("sandy", {"text": "Sorry, I'm not sure how to do that."})]

    asyncio.run(run())
