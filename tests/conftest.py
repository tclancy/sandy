"""Shared pytest fixtures for the Sandy test suite."""

import ast
import os
from pathlib import Path

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


#: Every `os.environ` method that takes a key as its first argument. An
#: allow-list, not a ban-list: `env_reads_without_a_literal_key` reports any
#: method outside this set and the one below, so a form nobody thought of shows
#: up as a test failure rather than as a variable that stops being scrubbed.
#: `pop` and `setdefault` are here because both *return* the ambient value —
#: `setdefault` is a write whose return value is a read.
ENVIRON_KEY_METHODS = frozenset({"get", "pop", "setdefault"})

#: `os.environ` methods that take no key at all. Nothing in `sandy/` uses one
#: today; they are listed so adding one is not mistaken for an unsupported read.
ENVIRON_KEYLESS_METHODS = frozenset({"clear", "copy", "items", "keys", "update", "values"})


def _is_environ(node: ast.AST) -> bool:
    """True for the `os.environ` / `environ` half of an env access.

    Matches on the attribute name alone, which also covers `import os as _os`
    and `from os import environ`. It would equally match a WSGI/CGI `environ`
    mapping; there is none in `sandy/` today, and
    `test_the_scrub_set_holds_no_process_critical_variable` is what keeps one
    from quietly adding `PATH` to the set every test runs without.
    """
    if isinstance(node, ast.Attribute):
        return node.attr == "environ"
    return isinstance(node, ast.Name) and node.id == "environ"


def _literal(node: ast.AST | None) -> str | None:
    """The node's value when it is a plain string literal, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _env_accesses(tree: ast.AST) -> list[tuple[ast.AST, str | None, str]]:
    """Every environment access in *tree*, as `(node, literal_key, form)`.

    `literal_key` is None when the key is computed — that is the blind spot the
    derivation cannot see, and `form` names which shape produced it so a
    reporter can say what it found.
    """
    found: list[tuple[ast.AST, str | None, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_environ(node.value):
            found.append((node, _literal(node.slice), "subscript"))
        elif isinstance(node, ast.Compare) and any(
            isinstance(op, ast.In | ast.NotIn) for op in node.ops
        ):
            if any(_is_environ(cmp) for cmp in node.comparators):
                found.append((node, _literal(node.left), "membership"))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            func = node.func
            first = node.args[0] if node.args else None
            if func.attr == "getenv":
                found.append((node, _literal(first), "getenv"))
            elif _is_environ(func.value):
                found.append((node, _literal(first), f"environ.{func.attr}"))
    return found


def env_keys_read_by_source(package_dir: Path) -> set[str]:
    """Every environment variable `package_dir`'s own code names, by AST.

    Covers `os.environ["X"]`, `"X" in os.environ`, `os.getenv("X")` and the
    key-taking `os.environ` methods in `ENVIRON_KEY_METHODS`. A computed key is
    invisible here; `test_env_isolation.py` pins that, so one arriving later is
    a visible failure rather than a variable that silently stops being scrubbed.

    Parsed from bytes rather than `read_text()`: 20 of the 28 files under
    `sandy/` hold non-ASCII, so a C locale would otherwise take the whole suite
    down at collection — the same class of machine-dependence this fixture set
    exists to remove.
    """
    keys: set[str] = set()
    for path in sorted(package_dir.rglob("*.py")):
        for _node, key, form in _env_accesses(ast.parse(path.read_bytes(), filename=str(path))):
            method = form.removeprefix("environ.")
            if form.startswith("environ.") and method not in ENVIRON_KEY_METHODS:
                continue
            if key is not None:
                keys.add(key)
    return keys


def env_reads_without_a_literal_key(package_dir: Path) -> list[str]:
    """Env accesses `env_keys_read_by_source` cannot enumerate, as `path:line`.

    Two shapes qualify: a computed key (`os.environ[prefix + name]`), and a
    method outside `ENVIRON_KEY_METHODS | ENVIRON_KEYLESS_METHODS`.

    **One exemption, and it is narrow**: a computed-key `setdefault`. Its only
    caller is `config.apply_env`, which writes the config file's own UPPERCASE
    keys under a loop variable — and those keys are exactly what
    `env_keys_declared_by_config` enumerates from the other direction, so they
    are not missing from the scrub set. A computed *read* has no such
    counterpart, which is why only this one method is exempt.
    """
    offenders: list[str] = []
    for path in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(path.read_bytes(), filename=str(path))
        for node, key, form in _env_accesses(tree):
            method = form.removeprefix("environ.")
            unsupported = form.startswith("environ.") and method not in (
                ENVIRON_KEY_METHODS | ENVIRON_KEYLESS_METHODS
            )
            computed = key is None and method not in ENVIRON_KEYLESS_METHODS
            if computed and method == "setdefault" and method in ENVIRON_KEY_METHODS:
                continue
            if unsupported or computed:
                offenders.append(f"{path.name}:{node.lineno} ({form})")
    return offenders


def env_keys_declared_by_config(example_path: Path) -> set[str]:
    """Every UPPERCASE key `sandy.toml.example` would push into `os.environ`.

    Mirrors `sandy.config.apply_env`'s own walk — globals, then one level of
    plugin section — because that is the contract the example file documents.
    Deliberately no deeper: `apply_env` does not reach a doubly-nested table
    either, and a derivation that is *more* thorough than the production code it
    models is describing a different system.

    This is the half the AST cannot see: `SPOTIPY_CLIENT_ID` is read by
    `spotipy` inside the library, never by a line in `sandy/`, and it is a
    credential. The example file rather than a real `sandy.toml`, deliberately —
    a machine-local file is the input this whole fixture set exists to remove.
    """
    config = config_module.load_config(example_path)
    keys = {key for key in config if key.isupper()}
    for value in config.values():
        if isinstance(value, dict):
            keys |= {key for key in value if key.isupper()}
    return keys


_REPO_ROOT = Path(__file__).resolve().parent.parent

#: Derived, never hand-maintained. A new plugin that reads a new variable, or a
#: new credential documented in the example config, joins this set on the next
#: run without anyone remembering to update a list (sandy#201).
AMBIENT_ENV_KEYS = env_keys_read_by_source(_REPO_ROOT / "sandy") | env_keys_declared_by_config(
    _REPO_ROOT / "sandy.toml.example"
)


def scrub_ambient_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every variable in `AMBIENT_ENV_KEYS` from the environment.

    Split out of the fixture below for the same reason as `scrub_git_env`: so
    the behaviour is testable as a plain function rather than through pytest
    privates.
    """
    for var in AMBIENT_ENV_KEYS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _scrub_ambient_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop inherited sandy configuration for the duration of each test.

    `_isolate_config` above closed the config-*file* channel into `os.environ`
    (sandy#200). This closes the *shell* one. They are the same harm — a suite
    whose outcome depends on machine-local state, green in CI and red on a
    developer box, failing while describing something unrelated — and the
    shell channel is the likelier of the two, because anyone who exports sandy
    keys from a shell profile instead of `sandy.toml` gets it (sandy#201).

    Measured on `41734fc`, before this fixture existed::

        SANDY_PRINTER=ipp://example.local/printers/x pytest tests/test_printer.py
        2 failed, 20 passed          # unset: 22 passed

    **One channel is deliberately left open, and no fixture can close it.**
    `sandy/daemon.py:25-26` reads `DEBUG` and `SENTRY_DSN` at *import* time,
    during collection, before any fixture runs. `DEBUG` and `SENTRY_DSN` are in
    the scrub set, so every *call-time* reader of them is covered, but the two
    module-level constants are already bound by then. Deferring those reads into
    a function is a production change and is sandy#201's open question, not
    something to smuggle in behind a test fixture.

    **Neither of the other two shapes the ticket floats would have worked**, and
    both fail for the same reason. Snapshot-and-restore never *removes* a value
    that was present when pytest started, which is precisely what the
    reproduction above is. Replacing `os.environ` wholesale via
    `monkeypatch.setattr` isolates writes but carries the ambient values into the
    copy, and a *filtered* copy needs this same derived key set to know what to
    filter. Both solve leakage between tests, which `monkeypatch` already solves.

    **One residual the derivation cannot reach**, named because the rest of this
    docstring is careful about its limits: a third-party library may read a key
    that appears neither in `sandy/` nor in the example config —
    `SENTRY_ENVIRONMENT`, `HTTPS_PROXY`. Measured: none of them turns this suite
    red today. `SPOTIPY_CLIENT_ID` is the same shape and *is* covered, because
    the example config documents it.

    The per-test `monkeypatch.delenv(..., raising=False)` calls in
    `test_youtube_tv.py`, `test_dispatch_plugin.py`, `test_hardcover.py` and
    `test_music_discovery.py` are redundant with this fixture now. They stay:
    each is that test's local declaration that it exercises the unset branch, and
    deleting them would couple those tests to this file.
    """
    scrub_ambient_env(monkeypatch)


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
