"""Tests for the Sandy progress reporting module."""

import asyncio
import io

from sandy.progress import CliProgressReporter, make_reporter


def test_reporter_writes_to_stderr():
    buf = io.StringIO()
    reporter = CliProgressReporter("spotify", file=buf)
    reporter("Fetching artists…")
    output = buf.getvalue()
    assert "spotify" in output
    assert "Fetching artists" in output


def test_reporter_clears_line():
    buf = io.StringIO()
    reporter = CliProgressReporter("spotify", file=buf)
    reporter("working…")
    reporter.clear()
    # After clear, there should be spaces to overwrite the previous message
    output = buf.getvalue()
    assert "   " in output  # padding spaces present


def test_reporter_clear_when_inactive_is_noop():
    buf = io.StringIO()
    reporter = CliProgressReporter("spotify", file=buf)
    # Never called — clear should not write anything
    reporter.clear()
    assert buf.getvalue() == ""


def test_reporter_overwrites_with_carriage_return():
    buf = io.StringIO()
    reporter = CliProgressReporter("test", file=buf)
    reporter("step 1")
    reporter("step 2")
    output = buf.getvalue()
    # Each write starts with \r so it overwrites the previous line
    assert output.count("\r") >= 2


def test_make_reporter_returns_cli_reporter():
    r = make_reporter("myplug")
    assert isinstance(r, CliProgressReporter)


def test_queue_progress_reporter_sends_message():
    """QueueProgressReporter puts formatted messages on the queue."""
    from sandy.progress import QueueProgressReporter

    async def run():
        loop = asyncio.get_running_loop()
        q = asyncio.Queue()
        reporter = QueueProgressReporter("spotify", q, loop)
        reporter("Loading artists…")
        # Give the event loop a chance to process the call_soon_threadsafe
        await asyncio.sleep(0)
        msg = q.get_nowait()
        assert msg == "[spotify] Loading artists…"

    asyncio.run(run())


def test_queue_progress_reporter_clear_is_noop():
    """clear() on QueueProgressReporter doesn't raise."""
    from sandy.progress import QueueProgressReporter

    async def run():
        loop = asyncio.get_running_loop()
        q = asyncio.Queue()
        reporter = QueueProgressReporter("test", q, loop)
        reporter.clear()  # should not raise

    asyncio.run(run())
