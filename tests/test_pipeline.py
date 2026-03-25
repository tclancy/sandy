"""Tests for the Sandy pipeline module."""

import textwrap
from unittest.mock import MagicMock


from sandy.pipeline import _accepts_progress, run_pipeline


def _make_plugin(name, commands, handle_src):
    """Compile a plugin object from inline source."""
    lines = [
        f"name = {name!r}",
        f"commands = {commands!r}",
    ] + textwrap.dedent(handle_src).splitlines()
    code = "\n".join(lines)
    ns = {}
    exec(compile(code, f"<plugin:{name}>", "exec"), ns)
    mod = type(
        "Plugin",
        (),
        {"name": ns["name"], "commands": ns["commands"], "handle": staticmethod(ns["handle"])},
    )
    return mod()


# ---------------------------------------------------------------------------
# _accepts_progress
# ---------------------------------------------------------------------------


class _WithProgress:
    name = "wp"
    commands = ["test"]

    def handle(self, text, actor, progress=None):
        return "ok"


class _WithoutProgress:
    name = "np"
    commands = ["test"]

    def handle(self, text, actor):
        return "ok"


def test_accepts_progress_true():
    assert _accepts_progress(_WithProgress()) is True


def test_accepts_progress_false():
    assert _accepts_progress(_WithoutProgress()) is False


def test_accepts_progress_bad_plugin():
    """A plugin whose handle() can't be introspected returns False, not an error."""

    class Broken:
        name = "broken"
        handle = None  # not callable

    assert _accepts_progress(Broken()) is False


# ---------------------------------------------------------------------------
# run_pipeline — basic routing
# ---------------------------------------------------------------------------


def test_run_pipeline_returns_results():
    plugin = _make_plugin("echo", ["hello"], "def handle(text, actor): return f'hi {actor}'")
    results, errors = run_pipeline("hello world", "tom", plugins=[plugin])
    assert errors == []
    assert len(results) == 1
    name, response = results[0]
    assert name == "echo"
    assert response == "hi tom"


def test_run_pipeline_no_match():
    results, errors = run_pipeline("zzz unknown", "tom", plugins=[])
    assert results == []
    assert errors == []


def test_run_pipeline_plugin_error():
    plugin = _make_plugin("boom", ["boom"], "def handle(text, actor): raise RuntimeError('kaboom')")
    results, errors = run_pipeline("boom", "tom", plugins=[plugin])
    assert results == []
    assert len(errors) == 1
    plugin_name, error_msg = errors[0]
    assert plugin_name == "boom"
    assert "kaboom" in error_msg


def test_run_pipeline_partial_failure():
    good = _make_plugin("good", ["test"], "def handle(text, actor): return 'good'")
    bad = _make_plugin("bad", ["test"], "def handle(text, actor): raise ValueError('oops')")
    results, errors = run_pipeline("test", "tom", plugins=[good, bad])
    assert len(results) == 1
    assert results[0][0] == "good"
    assert len(errors) == 1
    plugin_name, error_msg = errors[0]
    assert plugin_name == "bad"
    assert "oops" in error_msg


# ---------------------------------------------------------------------------
# run_pipeline — progress support
# ---------------------------------------------------------------------------


def test_run_pipeline_passes_progress_to_supporting_plugin():
    handle_src = textwrap.dedent("""
        def handle(text, actor, progress=None):
            if progress:
                progress('step1')
            return 'done'
    """)
    plugin = _make_plugin("prog", ["prog"], handle_src)

    calls = []

    def factory(plugin_name):
        reporter = MagicMock()
        reporter.side_effect = lambda msg: calls.append((plugin_name, msg))
        reporter.clear = MagicMock()
        return reporter

    results, errors = run_pipeline("prog", "tom", plugins=[plugin], progress_factory=factory)
    assert errors == []
    assert results[0][1] == "done"
    assert any(msg == "step1" for _, msg in calls)


def test_run_pipeline_progress_cleared_on_success():
    handle_src = textwrap.dedent("""
        def handle(text, actor, progress=None):
            if progress:
                progress('working')
            return 'ok'
    """)
    plugin = _make_plugin("p", ["go"], handle_src)
    reporter = MagicMock()
    reporter.clear = MagicMock()

    def factory(name):
        return reporter

    run_pipeline("go", "tom", plugins=[plugin], progress_factory=factory)
    reporter.clear.assert_called_once()


def test_run_pipeline_progress_cleared_on_failure():
    handle_src = textwrap.dedent("""
        def handle(text, actor, progress=None):
            if progress:
                progress('working')
            raise RuntimeError('boom')
    """)
    plugin = _make_plugin("p", ["go"], handle_src)
    reporter = MagicMock()
    reporter.clear = MagicMock()

    def factory(name):
        return reporter

    run_pipeline("go", "tom", plugins=[plugin], progress_factory=factory)
    reporter.clear.assert_called_once()


def test_run_pipeline_no_progress_for_non_supporting_plugin():
    """Progress factory is called but reporter is NOT passed to plugin that lacks the param."""
    plugin = _make_plugin("np", ["go"], "def handle(text, actor): return 'ok'")
    reporter = MagicMock()
    reporter.clear = MagicMock()

    def factory(name):
        return reporter

    results, errors = run_pipeline("go", "tom", plugins=[plugin], progress_factory=factory)
    # reporter should NOT have been called as a progress fn (plugin doesn't accept it)
    assert not reporter.called
    # but clear should still be called
    reporter.clear.assert_called_once()
