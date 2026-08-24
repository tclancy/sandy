import asyncio
import os
import re
import textwrap
import time
from unittest.mock import patch

import pytest

from sandy.daemon import Daemon, _missing_required_plugins, _plugin_snapshot


# ---------------------------------------------------------------------------
# _missing_required_plugins
# ---------------------------------------------------------------------------


def test_missing_required_plugins_lists_absent_names():
    assert _missing_required_plugins({"a", "b"}, "a, c ,d") == ["c", "d"]


def test_missing_required_plugins_empty_when_all_present():
    assert _missing_required_plugins({"a", "b"}, "a,b") == []


def test_missing_required_plugins_empty_when_unset():
    assert _missing_required_plugins({"a"}, "") == []


def test_daemon_reports_missing_required_plugin_to_sentry(tmp_path, monkeypatch, sentry_events):
    """A required plugin that fails to load fires a Sentry alert at startup."""
    monkeypatch.setenv("SANDY_REQUIRED_PLUGINS", "echo,itguy")
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

    Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    import sentry_sdk

    sentry_sdk.flush()
    assert len(sentry_events) == 1
    assert "itguy" in sentry_events[0]["message"]
    assert sentry_events[0]["tags"]["missing"] == "itguy"


def test_daemon_silent_when_all_required_plugins_present(tmp_path, monkeypatch, sentry_events):
    monkeypatch.setenv("SANDY_REQUIRED_PLUGINS", "echo")
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

    Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    import sentry_sdk

    sentry_sdk.flush()
    assert sentry_events == []


@pytest.fixture(autouse=True)
def no_entry_points(monkeypatch):
    """Suppress real entry-point discovery in all daemon tests by default."""
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points",
        lambda group=None, **kwargs: [],
    )


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
    """Daemon callback sends the didn't-understand reply when no plugins match.

    Calls ``_handle_callback`` directly. The previous version of this test
    rebuilt the callback's body inline and asserted on its own copy, so it
    would have stayed green through any change to the daemon (sandy#183).
    """
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

        with patch("sandy.daemon.voice.opening_aside", return_value=None):
            await daemon._handle_callback("wibble the frobnitz", "tom", reply_fn)

        assert len(replies) == 1
        name, resp = replies[0]
        assert name == "sandy"
        assert "wibble the frobnitz" in resp["text"]
        assert "help" in resp["text"].lower()

    asyncio.run(run())


# --- voice: one aside per interaction, at the delivery boundary (sandy#183) ---


def test_callback_opens_with_the_aside_on_the_first_reply_only(tmp_path):
    """Sandy fans out — the aside belongs to the interaction, not the response."""
    plugin_dir = _make_plugins(
        tmp_path,
        "plugins",
        {
            "alpha.py": """
            name = "alpha"
            commands = ["test"]
            def handle(text, actor):
                return {"text": "alpha answer"}
        """,
            "beta.py": """
            name = "beta"
            commands = ["test"]
            def handle(text, actor):
                return {"text": "beta answer"}
        """,
        },
    )
    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        replies = []

        async def reply_fn(name, resp):
            replies.append((name, resp))

        with patch("sandy.daemon.voice.opening_aside", return_value="You're up early, Tom."):
            await daemon._handle_callback("test", "tom", reply_fn)

        texts = [resp["text"] for _, resp in replies]
        assert len(texts) == 2
        assert sum("You're up early, Tom." in t for t in texts) == 1
        assert texts[0].startswith("You're up early, Tom.")
        assert "alpha answer" in texts[0]
        assert "beta answer" in texts[1]

    asyncio.run(run())


def test_callback_stays_quiet_when_the_hour_is_unremarkable(tmp_path):
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

        with patch("sandy.daemon.voice.opening_aside", return_value=None):
            await daemon._handle_callback("echo this", "tom", reply_fn)

        assert replies == [("echo", {"text": "ok"})]

    asyncio.run(run())


def test_callback_carries_the_aside_on_the_unmatched_reply(tmp_path):
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

        with patch("sandy.daemon.voice.opening_aside", return_value="Wow, you're up late, Tom."):
            await daemon._handle_callback("wibble", "tom", reply_fn)

        assert replies[0][1]["text"].startswith("Wow, you're up late, Tom.")
        assert "wibble" in replies[0][1]["text"]

    asyncio.run(run())


def test_callback_does_not_put_the_aside_on_a_progress_update(tmp_path):
    """Progress lines are Sandy thinking out loud, not the reply she opens with."""
    plugin_dir = _make_plugins(
        tmp_path,
        "plugins",
        {
            "slow.py": """
            name = "slow"
            commands = ["slow"]
            def handle(text, actor, progress=None):
                if progress:
                    progress("working on it")
                return {"text": "done"}
        """
        },
    )
    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        replies = []

        async def reply_fn(name, resp):
            replies.append((name, resp))

        with patch("sandy.daemon.voice.opening_aside", return_value="You're up early, Tom."):
            await daemon._handle_callback("slow", "tom", reply_fn)

        by_name = {name: resp for name, resp in replies}
        assert "You're up early, Tom." not in by_name["progress"]["text"]
        assert by_name["slow"]["text"].startswith("You're up early, Tom.")

    asyncio.run(run())


def test_callback_passes_the_actor_and_timezone_to_the_voice(tmp_path):
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
        async def reply_fn(name, resp):
            pass

        with patch("sandy.daemon.voice.opening_aside", return_value=None) as spy:
            await daemon._handle_callback("echo this", "michelle", reply_fn, tz="Europe/London")

        assert spy.call_args.args[0] == "michelle"
        assert spy.call_args.kwargs["tz"] == "Europe/London"

    asyncio.run(run())


def test_callback_plugin_error_includes_detail(tmp_path):
    """Daemon callback appends truncated error detail (in backticks) to the friendly message."""
    plugin_dir = _make_plugins(
        tmp_path,
        "plugins",
        {
            "bad.py": """
            name = "bad"
            commands = ["break things"]
            def handle(text, actor):
                raise RuntimeError("Something went wrong: API key missing")
        """
        },
    )
    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        replies = []

        async def reply_fn(name, resp):
            replies.append((name, resp))

        await daemon._handle_callback("break things", "tom", reply_fn)

        assert len(replies) == 1
        name, resp = replies[0]
        assert name == "error"
        assert "bad" in resp["text"]
        assert "does not want to behave" in resp["text"]
        assert "`Something went wrong: API key missing`" in resp["text"]

    asyncio.run(run())


def test_callback_plugin_error_truncates_long_message(tmp_path):
    """Daemon callback truncates error detail to 100 characters."""
    long_msg = "x" * 150
    plugin_dir = _make_plugins(
        tmp_path,
        "plugins",
        {
            "bad.py": f"""
            name = "bad"
            commands = ["break things"]
            def handle(text, actor):
                raise RuntimeError("{long_msg}")
        """
        },
    )
    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        replies = []

        async def reply_fn(name, resp):
            replies.append((name, resp))

        await daemon._handle_callback("break things", "tom", reply_fn)

        assert len(replies) == 1
        _, resp = replies[0]
        # backtick-wrapped detail should be at most 100 chars + backticks
        match = re.search(r"`([^`]+)`", resp["text"])
        assert match is not None
        assert len(match.group(1)) == 100

    asyncio.run(run())


def test_callback_plugin_error_no_message_omits_backticks(tmp_path):
    """Daemon callback omits backtick detail when exception has no message."""
    plugin_dir = _make_plugins(
        tmp_path,
        "plugins",
        {
            "bad.py": """
            name = "bad"
            commands = ["break things"]
            def handle(text, actor):
                raise RuntimeError()
        """
        },
    )
    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        replies = []

        async def reply_fn(name, resp):
            replies.append((name, resp))

        await daemon._handle_callback("break things", "tom", reply_fn)

        assert len(replies) == 1
        _, resp = replies[0]
        assert "does not want to behave" in resp["text"]
        assert "`" not in resp["text"]

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
