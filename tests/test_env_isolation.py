"""The shell channel into `os.environ`, and the guards that keep it closed.

`tests/test_config_isolation.py` covers the *file* channel (sandy#200): a
`sandy.toml` on the machine being discovered and applied mid-suite. This module
covers the *shell* one (sandy#201): variables that were already in `os.environ`
when pytest started, which no amount of config pinning can reach.

The fixture under test derives its own scrub set rather than carrying a list,
so the tests here are aimed at the derivation as much as at the scrub — a
parser that quietly returns nothing produces an empty scrub set, a fixture that
removes nothing, and a suite that stays green all the way through.
"""

import ast
import os
from pathlib import Path

import pytest

from tests import conftest


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_the_ambient_scrub_is_registered_and_actually_scrubs(request):
    """Registration, behaviour and wiring — three independent ways to break.

    Copied deliberately from `test_the_conftest_scrub_is_registered_and_actually_scrubs`
    in `test_repo_hygiene.py`, which records why the third arm is needed: a
    fixture body emptied to `return None` passed both of the others.

    Asserting "no `SANDY_PRINTER` in `os.environ` during a test" would be the
    obvious check and is worthless — on a machine that never exported it, it
    passes against a deleted fixture. That is exactly how this bug survived
    sandy#200.
    """
    assert "_scrub_ambient_env" in request.fixturenames, (
        "_scrub_ambient_env is not active for this test — it has been deleted "
        "or is no longer autouse, so every test is readable by the developer's "
        "shell again."
    )

    # Behaviour, via the plain function — no pytest internals.
    inner = pytest.MonkeyPatch()
    try:
        inner.setenv("SANDY_PRINTER", "ipp://decoy.invalid/printers/x")
        inner.setenv("HARDCOVER_API_KEY", "decoy")

        conftest.scrub_ambient_env(inner)

        assert "SANDY_PRINTER" not in os.environ
        assert "HARDCOVER_API_KEY" not in os.environ
    finally:
        inner.undo()

    # Wiring. Invoking a fixture's body outside a pytest run needs
    # `_fixture_function`; `test_repo_hygiene.py` records why that version
    # dependency is worth taking, and this is the same reach for the same reason.
    setup = pytest.MonkeyPatch()
    try:
        setup.setenv("SANDY_PRINTER", "ipp://decoy.invalid/printers/x")
        assert "SANDY_PRINTER" in os.environ, "monkeypatch setup above did not take"
        wiring = pytest.MonkeyPatch()
        try:
            conftest._scrub_ambient_env._fixture_function(wiring)
            assert "SANDY_PRINTER" not in os.environ, (
                "the _scrub_ambient_env fixture body ran without scrubbing "
                "anything — it is registered and autouse but no longer calls "
                "scrub_ambient_env, so every test in the suite is exposed to "
                "the shell while this module still reports green."
            )
        finally:
            wiring.undo()
    finally:
        setup.undo()


def test_both_derivation_sources_contribute_keys_the_other_misses():
    """The reachability control for the scrub set.

    `AMBIENT_ENV_KEYS` is a union, so asserting "every derived key is in the
    scrub set" is a tautology — it would pass just as happily over two parsers
    that both return nothing. What can actually break is a *parser*, so each is
    pinned against a key only it can see:

    - `SANDY_PRINTER` is read at `sandy/printer.py:273` and appears nowhere in
      `sandy.toml.example`. Only the AST walk finds it.
    - `SPOTIPY_CLIENT_ID` is read by `spotipy` inside the library — no line in
      `sandy/` mentions it — and is documented in the example config. Only the
      config walk finds it. It is also a credential.

    Measured on `41734fc`: 22 keys from source, 17 from config, 26 in the union.
    """
    from_source = conftest.env_keys_read_by_source(REPO_ROOT / "sandy")
    from_config = conftest.env_keys_declared_by_config(REPO_ROOT / "sandy.toml.example")

    assert "SANDY_PRINTER" in from_source
    assert "SANDY_PRINTER" not in from_config, (
        "SANDY_PRINTER is now in the example config too, so it no longer "
        "discriminates — pick another source-only key for this control."
    )
    assert "SPOTIPY_CLIENT_ID" in from_config
    assert "SPOTIPY_CLIENT_SECRET" in conftest.AMBIENT_ENV_KEYS, (
        "a credential read by a third-party library dropped out of the scrub set"
    )
    assert from_source - from_config, "the AST walk contributes nothing unique"
    assert from_config - from_source, "the config walk contributes nothing unique"


#: One module exercising every read form the derivation claims to support, plus
#: every form it claims to be blind to. The parsers are otherwise tested only
#: against the live `sandy/` tree, which happens to use exactly one of them —
#: four parser branches could be deleted with the whole suite staying green
#: before this fixture existed.
_EVERY_READ_FORM = """\
import os
from os import environ

computed = "SANDY_" + "COMPUTED"

a = os.environ["SUBSCRIPT"]
b = os.environ.get("GET")
c = os.getenv("GETENV")
d = os.environ.pop("POP", None)
e = os.environ.setdefault("SETDEFAULT", "x")
f = environ["BARE_NAME"]
g = "MEMBERSHIP" in os.environ
h = "NOT_MEMBERSHIP" not in os.environ
"""

_EVERY_BLIND_FORM = """\
import os

name = "X"

a = os.environ[name]
b = os.environ.get(name)
c = os.getenv(name)
d = name in os.environ
e = os.environ.somethingnobodysupports("LITERAL")
"""


def _write(tmp_path: Path, source: str, name: str = "pkg") -> Path:
    package = tmp_path / name
    package.mkdir(parents=True)
    (package / "mod.py").write_text(source)
    return package


def test_the_ast_walk_finds_every_read_form_it_claims_to_support(tmp_path):
    """Pins each parser branch against a form only that branch can see.

    Without this, four branches were dead weight that the suite could not tell
    from working code. `sandy/`'s only two subscript reads name keys that the
    example config *also* declares, so deleting the subscript branch left the
    union byte-identical at 26 keys; `os.getenv` and bare-name `environ` appear
    nowhere in `sandy/` at all.
    """
    package = _write(tmp_path, _EVERY_READ_FORM)

    assert conftest.env_keys_read_by_source(package) == {
        "SUBSCRIPT",
        "GET",
        "GETENV",
        "POP",
        "SETDEFAULT",
        "BARE_NAME",
        "MEMBERSHIP",
        "NOT_MEMBERSHIP",
    }


def test_the_ast_walk_reports_every_form_it_cannot_enumerate(tmp_path):
    """The reachability control for the absence assertion below.

    `test_no_environment_read_in_sandy_is_invisible_to_the_derivation` asserts
    an empty list, which is exactly what a detector matching nothing returns.
    A control that writes only *one* blind shape is not enough either: with a
    single computed subscript in the decoy, the whole computed-`.get` branch
    could be deleted and both tests stayed green.
    """
    package = _write(tmp_path, _EVERY_BLIND_FORM)

    offenders = conftest.env_reads_without_a_literal_key(package)

    assert len(offenders) == 5, offenders
    assert [o.split()[-1] for o in offenders] == [
        "(subscript)",
        "(environ.get)",
        "(getenv)",
        "(membership)",
        "(environ.somethingnobodysupports)",
    ]


def test_the_config_walk_reads_globals_and_one_level_of_section(tmp_path):
    """Both halves of `apply_env`'s contract, and the limit past them.

    `sandy.toml.example` happens to declare every key inside a plugin section,
    so the globals half of the walk is unexercised by the real file and could be
    deleted with the suite green. The third key here pins the *limit* as much as
    the coverage: `apply_env` does not descend two levels, so neither does this.
    """
    example = tmp_path / "sandy.toml"
    example.write_text(
        'GLOBAL_KEY = "a"\nlowercase = "ignored"\n\n'
        '[plugin]\nSECTION_KEY = "b"\nalso_lowercase = "ignored"\n\n'
        '[plugin.nested]\nTOO_DEEP = "c"\n'
    )

    assert conftest.env_keys_declared_by_config(example) == {"GLOBAL_KEY", "SECTION_KEY"}


def test_a_computed_setdefault_is_the_one_exempt_shape(tmp_path):
    """The exemption, pinned — and pinned as narrow.

    `config.apply_env` writes the config file's own keys under a loop variable.
    Those keys are covered from the other side by `env_keys_declared_by_config`,
    so reporting them would be noise. Every *other* computed form stays
    reported, which is what stops the exemption becoming a hole.
    """
    package = _write(tmp_path, 'import os\nk = "X"\nos.environ.setdefault(k, "v")\n')
    assert conftest.env_reads_without_a_literal_key(package) == []

    package_get = _write(tmp_path, 'import os\nk = "X"\nv = os.environ.get(k)\n', name="other")
    assert conftest.env_reads_without_a_literal_key(package_get) != []


def test_no_environment_read_in_sandy_is_invisible_to_the_derivation():
    """The derivation's blind spot, asserted empty rather than assumed away."""
    offenders = conftest.env_reads_without_a_literal_key(REPO_ROOT / "sandy")

    assert offenders == [], (
        f"{len(offenders)} environment access(es) in sandy/ cannot be enumerated "
        f"({offenders[:3]}) — conftest.env_keys_read_by_source does not see them, "
        "so those variables are no longer scrubbed between tests. Either use a "
        "literal key and a supported method, or widen ENVIRON_KEY_METHODS."
    )


def test_the_scrub_set_holds_no_process_critical_variable():
    """`_is_environ` matches any attribute named `environ`, WSGI included.

    There is no WSGI/CGI `environ` in `sandy/` today. If one arrives, its
    `environ["PATH_INFO"]` reads would join the set an autouse fixture deletes
    from every test in the suite — and `PATH` or `HOME` going missing mid-test
    fails a long way from its cause.
    """
    process_critical = {
        "CI",
        "HOME",
        "LANG",
        "PATH",
        "PATH_INFO",
        "PYTHONPATH",
        "TMPDIR",
        "USER",
        "VIRTUAL_ENV",
    }

    caught = sorted(conftest.AMBIENT_ENV_KEYS & process_critical)

    assert caught == [], (
        f"the derived scrub set has picked up {caught}, which an autouse "
        "fixture now removes from every test in the suite."
    )


def test_daemon_still_reads_debug_and_sentry_dsn_at_import_time():
    """sandy#201 channel 2, which no fixture can close — recorded, not fixed.

    `DEBUG` and `SENTRY_DSN` are in the scrub set, so every *call-time* reader of
    them is isolated. The two module-level constants in `sandy/daemon.py` are
    bound during collection, before any fixture runs, and deferring those reads
    into a function is a production change with its own decision to make.

    Matched on module scope rather than on a top-level `ast.Assign`, so renaming
    the call to `os.getenv`, annotating the assignment, or wrapping it in a
    module-level `if` does not read as "the channel is closed".
    """
    tree = ast.parse((REPO_ROOT / "sandy" / "daemon.py").read_bytes())
    inside_a_function = {
        id(node)
        for scope in ast.walk(tree)
        if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef)
        for node in ast.walk(scope)
    }
    keys = {
        key
        for node, key, _form in conftest._env_accesses(tree)
        if id(node) not in inside_a_function
    }

    assert keys == {"DEBUG", "SENTRY_DSN"}, (
        f"sandy/daemon.py's import-time environment reads are now {keys}. If they "
        "moved into a function, sandy#201 channel 2 is closed — confirm that "
        "before deleting this test and the paragraph about it in "
        "conftest._scrub_ambient_env."
    )
