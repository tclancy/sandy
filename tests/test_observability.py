"""Tests for sandy.observability — Sentry init and the capture() helper."""

import pytest
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from sandy.observability import capture, init_sentry, status_message


@pytest.fixture(autouse=True)
def _reset_sentry():
    """Ensure each test starts and ends with Sentry uninitialized."""
    sentry_sdk.get_global_scope().set_client(None)
    yield
    sentry_sdk.get_global_scope().set_client(None)


def _init_capturing():
    """Initialize Sentry, capturing events via before_send; return the event list."""
    events: list[dict] = []

    def _before_send(event, _hint):
        events.append(event)
        return None  # drop the event — never hit the network

    sentry_sdk.init(dsn="https://public@example.com/1", before_send=_before_send)
    return events


# ---------------------------------------------------------------------------
# init_sentry
# ---------------------------------------------------------------------------


def test_init_sentry_skips_when_dsn_empty():
    assert init_sentry("", debug=False) is False
    assert sentry_sdk.is_initialized() is False


def test_init_sentry_skips_when_debug_even_with_dsn():
    assert init_sentry("https://public@example.com/1", debug=True) is False
    assert sentry_sdk.is_initialized() is False


def test_init_sentry_activates_with_dsn_and_not_debug():
    assert init_sentry("https://public@example.com/1", debug=False) is True
    assert sentry_sdk.is_initialized() is True


def test_init_sentry_does_not_auto_capture_logs_as_events():
    """Logging must not silently become Sentry events — reporting is explicit
    via capture(), so events are tagged and never duplicated."""
    init_sentry("https://public@example.com/1", debug=False)
    integration = sentry_sdk.get_client().get_integration(LoggingIntegration)
    assert integration is not None
    assert integration._handler is None  # no EventHandler => logger.error sends nothing


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------


def test_capture_exception_sends_event_with_traceback_and_tags():
    events = _init_capturing()
    try:
        raise RuntimeError("subprocess blew up")
    except RuntimeError as exc:
        capture(exc, plugin="itguy")
    sentry_sdk.flush()

    assert len(events) == 1
    assert "exception" in events[0]
    assert events[0]["tags"]["plugin"] == "itguy"


def test_capture_string_sends_error_level_message():
    events = _init_capturing()
    capture("Spotify auth failed", plugin="spotify")
    sentry_sdk.flush()

    assert len(events) == 1
    assert events[0]["message"] == "Spotify auth failed"
    assert events[0]["level"] == "error"
    assert events[0]["tags"]["plugin"] == "spotify"


def test_capture_is_noop_when_sentry_uninitialized():
    # No init: is_initialized() is False. capture() must not raise.
    assert sentry_sdk.is_initialized() is False
    capture(RuntimeError("ignored"), plugin="anything")  # must not raise


# ---------------------------------------------------------------------------
# status_message
# ---------------------------------------------------------------------------


def test_status_message_active():
    assert "active" in status_message(True).lower()


def test_status_message_inactive_explains_why():
    msg = status_message(False).lower()
    assert "inactive" in msg
    assert "sentry_dsn" in msg or "debug" in msg
