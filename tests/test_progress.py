"""Tests for the Sandy progress reporting module."""

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
