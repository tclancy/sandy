"""Shared pytest fixtures for the Sandy test suite."""

import os

import pytest
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration


def scrub_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every `GIT_*` variable from the environment via `monkeypatch`.

    Split out of the fixture below so the behaviour can be tested as a plain
    function. Testing it through the fixture object would mean reaching into
    pytest privates (`_fixture_function`), which is a needless version
    dependency for a four-line loop.
    """
    for var in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _scrub_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every inherited `GIT_*` variable for the duration of each test.

    Git exports `GIT_DIR` and `GIT_INDEX_FILE` into the environment of every
    hook it runs, and `.pre-commit-config.yaml` runs this suite from a
    `pytest-cov` hook with `always_run: true`. `GIT_DIR` beats both `cwd=` and
    `-C`, so a test that shells out to git would read whichever repository the
    ambient `GIT_DIR` names instead of this one (sandy#173).

    **This is a safety net, not the fix, and it must not be mistaken for one.**
    A conftest scrub turns a suite green while leaving the code that runs git
    still redirectable — that is the homelab#329 lesson, where the real defect
    was in a deployed script and scrubbing here would have hidden it. So the
    rule this fixture does *not* relax: **any code that runs git scrubs its own
    environment.** `tests/test_repo_hygiene.py:git_env` is the shape to copy.

    Sandy differs from homelab in one way worth recording, because it bounds
    how much this fixture is covering for: **no production code in `sandy/` or
    `deploy/` shells out to git** — verified by grep while fixing sandy#173 —
    so unlike homelab there is no deployed caller for a conftest scrub to mask.
    If that ever stops being true, the new caller needs its own `git_env()`,
    not a reliance on this.

    Tests that specifically pin the redirect set `GIT_DIR` themselves *after*
    this fixture has run, which is why
    `test_git_dir_in_the_environment_cannot_redirect_the_root` still bites.
    """
    scrub_git_env(monkeypatch)


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


@pytest.fixture(autouse=True)
def _silence_the_voice(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence Sandy's time-of-day aside for the duration of each test.

    ``sandy.voice.opening_aside`` reads the wall clock, so any test that
    asserts on delivered response text would pass at 2 p.m. and fail at 3 a.m.
    — the two existing daemon tests that pin an exact reply string did exactly
    that when the voice landed (sandy#183). Freezing the nondeterminism here
    keeps the rest of the suite time-independent.

    This hides nothing: ``tests/test_voice.py`` exercises the real function
    directly, and the boundary tests in ``test_cli.py`` / ``test_daemon.py``
    patch ``voice.opening_aside`` themselves with a fixed aside, which
    overrides this fixture and proves the wiring.

    Tests of the voice itself carry ``@pytest.mark.real_voice`` and are left
    alone.
    """
    if "real_voice" in request.keywords:
        return
    monkeypatch.setattr("sandy.voice.opening_aside", lambda *a, **kw: None)
