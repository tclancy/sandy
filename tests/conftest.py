"""Shared pytest fixtures for the Sandy test suite."""

import os

import pytest
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

import sandy.config as config_module


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ambient config files invisible to every test.

    `sandy.config.find_config_path` walks `_SEARCH_PATHS` at call time, and
    `apply_env` then copies every UPPERCASE key it finds into `os.environ` with
    `setdefault`. Any test that reaches `load_config()` without pinning a path
    — a bare `Daemon(...)`, `main()`, or `run_pipeline()` — therefore imports
    whatever config the machine happens to have, and those values persist for
    every test that runs afterwards (sandy#200).

    Pinning the list to empty is sufficient and precise: nothing is discovered,
    nothing is applied, and a test that genuinely exercises discovery overrides
    it with its own `setattr` on the same function-scoped `monkeypatch` —
    `tests/test_help_plugin.py` does exactly that and is unaffected.

    The credential exposure is the loud harm, but the quiet one costs more
    time: ambient config can turn a run red *for the wrong reason*. An
    `[actors]` section that does not resolve the actor a test passes makes
    `run_pipeline` return an access-denied **result** rather than an empty one,
    so a test about the no-match branch never reaches that branch and fails
    describing something else entirely. That failure appears only on the
    developer's machine and never in CI, which is the expensive direction.

    Because this fixture is autouse and module-level fixtures shadow conftest
    ones **by name**, do not re-declare `_isolate_config` in a test module —
    a local copy silently replaces this one and stops tracking it. Override the
    behaviour with a plain `monkeypatch.setattr` inside the test instead.

    **The search path that actually fires here is `./sandy.toml`, not
    `~/.config/sandy/sandy.toml`.** `_SEARCH_PATHS` holds `Path("sandy.toml")`
    unresolved, so it is relative to the *current working directory* — which
    for this suite is the repo root, where a real gitignored `sandy.toml` is
    the documented local-dev location. This matters for anyone trying to
    reproduce the leak: it does **not** reproduce from a scratch checkout or
    in CI, because neither has that file. It reproduces in the one place the
    suite is usually run.
    """
    monkeypatch.setattr(config_module, "_SEARCH_PATHS", [])


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
