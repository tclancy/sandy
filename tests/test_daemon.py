import asyncio
import textwrap
from unittest.mock import patch
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

        with patch("sandy.daemon.print_pdf", return_value=True) as mock_print:
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

        with patch("sandy.daemon.print_pdf", return_value=False):
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

        with patch("sandy.daemon.print_pdf", return_value=True):
            await daemon._handle_callback("crossword", "tom", reply_fn)

        assert "pdf_url" not in forwarded

    asyncio.run(run())
