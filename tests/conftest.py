"""Shared pytest fixtures for the Sandy test suite."""

import pytest
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration


@pytest.fixture
def sentry_events():
    """Initialize Sentry like production and yield a list of captured events.

    Mirrors ``sandy.observability.init_sentry`` (logging does NOT auto-create
    events) and routes every event into the returned list via ``before_send``
    instead of the network. The client is torn down afterward so global Sentry
    state never leaks between tests.
    """
    events: list[dict] = []
    sentry_sdk.init(
        dsn="https://public@example.com/1",
        integrations=[LoggingIntegration(event_level=None)],
        before_send=lambda event, _hint: events.append(event) or None,
    )
    try:
        yield events
    finally:
        sentry_sdk.flush()
        sentry_sdk.get_global_scope().set_client(None)
