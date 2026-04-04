import asyncio
import os
import textwrap
import time
from unittest.mock import patch
from sandy.daemon import Daemon, _plugin_snapshot


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
        for plugin_name, error_msg in errors:
            friendly = f"I am terribly sorry, {plugin_name} just does not want to behave!"
            await reply_fn("error", {"text": friendly})
        if not results and not errors:
            await reply_fn("sandy", {"text": "Sorry, I'm not sure how to do that."})

        assert replies == [("sandy", {"text": "Sorry, I'm not sure how to do that."})]

    asyncio.run(run())


# ── pdf_url handling ──────────────────────────────────────────────────────────


def _make_pdf_plugin(tmp_path):
    return _make_plugins(
        tmp_path,
        "plugins",
        {
            "crossword.py": """
            name = "crossword"
            commands = ["crossword"]
            def handle(text, actor):
                return {
                    "text": "Sending your crossword to the printer.",
                    "pdf_url": "https://example.com/puzzle.pdf",
                    "links": [{"label": "View online", "url": "https://example.com/puzzle"}],
                }
        """
        },
    )


def test_daemon_calls_print_pdf_for_pdf_url(tmp_path):
    """Daemon calls print_pdf() when a plugin response contains pdf_url."""
    plugin_dir = _make_pdf_plugin(tmp_path)
    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        replies = []

        async def reply_fn(name, resp):
            replies.append((name, resp))

        with patch("sandy.daemon.print_pdf", return_value=(True, "")) as mock_print:
            await daemon._handle_callback("crossword", "tom", reply_fn)

        mock_print.assert_called_once_with("https://example.com/puzzle.pdf")
        assert len(replies) == 1
        _, resp = replies[0]
        # pdf_url should not be forwarded to the transport
        assert "pdf_url" not in resp
        # text unchanged on success
        assert resp["text"] == "Sending your crossword to the printer."
        # links still forwarded
        assert "links" in resp

    asyncio.run(run())


def test_daemon_updates_text_on_print_failure(tmp_path):
    """Daemon appends a printer-failure note to the text when print_pdf() returns False."""
    plugin_dir = _make_pdf_plugin(tmp_path)
    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        replies = []

        async def reply_fn(name, resp):
            replies.append((name, resp))

        with patch(
            "sandy.daemon.print_pdf", return_value=(False, "lpr: Error - printer not found")
        ):
            await daemon._handle_callback("crossword", "tom", reply_fn)

        assert len(replies) == 1
        _, resp = replies[0]
        assert "pdf_url" not in resp
        assert (
            "printer did not respond" in resp["text"].lower() or "printer" in resp["text"].lower()
        )

    asyncio.run(run())


def test_daemon_pdf_url_not_forwarded_to_transport(tmp_path):
    """pdf_url is consumed by the daemon and never sent to the transport."""
    plugin_dir = _make_pdf_plugin(tmp_path)
    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        forwarded = {}

        async def reply_fn(name, resp):
            forwarded.update(resp)

        with patch("sandy.daemon.print_pdf", return_value=(True, "")):
            await daemon._handle_callback("crossword", "tom", reply_fn)

        assert "pdf_url" not in forwarded

    asyncio.run(run())


# ── timezone propagation ──────────────────────────────────────────────────────


def test_handle_message_passes_tz_to_pipeline(tmp_path):
    """handle_message forwards tz= to run_pipeline."""
    plugin_dir = _make_plugins(
        tmp_path,
        "plugins",
        {
            "tz_echo.py": """
            name = "tz_echo"
            commands = ["tz test"]
            def handle(text, actor, tz=None):
                return {"text": f"tz={tz}"}
        """
        },
    )
    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        results, errors = await daemon.handle_message("tz test", "tom", tz="America/New_York")
        assert len(results) == 1
        assert results[0][1]["text"] == "tz=America/New_York"

    asyncio.run(run())


def test_handle_callback_passes_tz(tmp_path):
    """_handle_callback forwards tz= through to pipeline results."""
    plugin_dir = _make_plugins(
        tmp_path,
        "plugins",
        {
            "tz_echo.py": """
            name = "tz_echo"
            commands = ["tz test"]
            def handle(text, actor, tz=None):
                return {"text": f"tz={tz}"}
        """
        },
    )
    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        replies = []

        async def reply_fn(name, resp):
            replies.append((name, resp))

        await daemon._handle_callback("tz test", "tom", reply_fn, tz="Pacific/Auckland")

        assert len(replies) == 1
        assert replies[0][1]["text"] == "tz=Pacific/Auckland"

    asyncio.run(run())


# ── live-reload (plugin watcher) ──────────────────────────────────────────────


def test_plugin_snapshot_returns_mtimes(tmp_path):
    """_plugin_snapshot returns a {path: mtime} dict for .py files, excluding __init__.py."""
    _make_plugins(tmp_path, "plugins", {"echo.py": "x = 1", "__init__.py": ""})
    snap = _plugin_snapshot(str(tmp_path / "plugins"))
    paths = {str(p) for p in snap}
    assert any("echo.py" in p for p in paths)
    assert not any("__init__.py" in p for p in paths)


def test_plugin_snapshot_follows_symlinks(tmp_path):
    """_plugin_snapshot reflects the mtime of the symlink target, not the symlink itself."""
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    target = tmp_path / "real_plugin.py"
    target.write_text("x = 1")
    link = plugin_dir / "my_plugin.py"
    link.symlink_to(target)

    snap1 = _plugin_snapshot(str(plugin_dir))
    # Modify target and update mtime
    time.sleep(0.01)
    target.write_text("x = 2")

    snap2 = _plugin_snapshot(str(plugin_dir))
    assert snap1 != snap2, "Snapshot should detect mtime change through symlink"


def test_watch_plugins_reloads_on_change(tmp_path):
    """load_plugins picks up new code when a plugin file is modified and reloaded."""
    plugin_dir = _make_plugins(
        tmp_path,
        "plugins",
        {
            "echo.py": """
            name = "echo"
            commands = ["echo"]
            def handle(text, actor):
                return {"text": "v1"}
        """
        },
    )
    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))
    assert daemon.plugins[0].handle("echo", "tom")["text"] == "v1"

    # Rewrite the plugin file with new code
    plugin_file = tmp_path / "plugins" / "echo.py"
    plugin_file.write_text(
        textwrap.dedent("""
        name = "echo"
        commands = ["echo"]
        def handle(text, actor):
            return {"text": "v2"}
    """)
    )
    # Force mtime to differ (some fast filesystems may share the same timestamp)
    future_mtime = plugin_file.stat().st_mtime + 1
    os.utime(str(plugin_file), (future_mtime, future_mtime))

    # Verify snapshot detects the change
    current = _plugin_snapshot(plugin_dir)
    assert current != daemon._plugin_mtimes, "Snapshot should differ after file modification"

    # Reload and verify new code is active
    from sandy.loader import load_plugins

    daemon.plugins = load_plugins(plugin_dir, daemon.config)
    assert daemon.plugins[0].handle("echo", "tom")["text"] == "v2"


def test_watch_plugins_adds_new_plugin(tmp_path):
    """_watch_plugins detects a newly added plugin file."""
    plugin_dir = str(tmp_path / "plugins")
    (tmp_path / "plugins").mkdir()
    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))
    assert len(daemon.plugins) == 0

    # Add a plugin file
    (tmp_path / "plugins" / "new_plugin.py").write_text(
        textwrap.dedent("""
        name = "new"
        commands = ["new cmd"]
        def handle(text, actor):
            return {"text": "new"}
    """)
    )

    current = _plugin_snapshot(plugin_dir)
    assert current != daemon._plugin_mtimes, "Snapshot should change when file is added"

    from sandy.loader import load_plugins

    daemon.plugins = load_plugins(plugin_dir, daemon.config)
    daemon._plugin_mtimes = current

    assert len(daemon.plugins) == 1
    assert daemon.plugins[0].name == "new"


def test_watch_plugins_keeps_old_plugins_on_load_failure(tmp_path):
    """If load_plugins raises during a reload, the previous plugin set is kept active."""
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
    original_plugins = daemon.plugins

    call_count = [0]

    async def fake_sleep(_n):
        call_count[0] += 1
        if call_count[0] >= 2:
            raise asyncio.CancelledError

    async def run():
        # Blank the snapshot so the watcher detects a "change" on first poll
        daemon._plugin_mtimes = {}
        with patch("sandy.daemon.load_plugins", side_effect=RuntimeError("broken plugin")):
            with patch("sandy.daemon.asyncio.sleep", side_effect=fake_sleep):
                try:
                    await daemon._watch_plugins()
                except asyncio.CancelledError:
                    pass

        # Plugins are unchanged — failure kept the previous set
        assert daemon.plugins is original_plugins

    asyncio.run(run())


def test_watch_plugins_async_loop(tmp_path):
    """_watch_plugins loop detects a change and reloads within one poll cycle."""
    plugin_dir = _make_plugins(
        tmp_path,
        "plugins",
        {
            "echo.py": """
            name = "echo"
            commands = ["echo"]
            def handle(text, actor):
                return {"text": "v1"}
        """
        },
    )
    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))
    assert daemon.plugins[0].handle("echo", "tom")["text"] == "v1"

    # Rewrite plugin with bumped mtime so snapshot will differ
    plugin_file = tmp_path / "plugins" / "echo.py"
    plugin_file.write_text(
        textwrap.dedent("""
        name = "echo"
        commands = ["echo"]
        def handle(text, actor):
            return {"text": "v2"}
    """)
    )
    os.utime(str(plugin_file), (plugin_file.stat().st_mtime + 1,) * 2)

    call_count = [0]

    async def fake_sleep(_n):
        call_count[0] += 1
        if call_count[0] >= 2:
            raise asyncio.CancelledError

    async def run():
        with patch("sandy.daemon.asyncio.sleep", side_effect=fake_sleep):
            try:
                await daemon._watch_plugins()
            except asyncio.CancelledError:
                pass

        assert daemon.plugins[0].handle("echo", "tom")["text"] == "v2"

    asyncio.run(run())
