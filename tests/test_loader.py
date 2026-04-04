import textwrap
import types
from unittest.mock import MagicMock

import pytest

from sandy.loader import load_plugins
from sandy.matcher import find_matches


@pytest.fixture(autouse=True)
def no_entry_points(monkeypatch):
    """Suppress real entry-point discovery in all loader tests by default.

    Tests that exercise entry-point loading call monkeypatch.setattr again
    to override this fixture with their own mock list.
    """
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points",
        lambda group=None, **kwargs: [],
    )


def _write_plugin(tmp_path, filename, content):
    """Helper to write a plugin file into a temp directory."""
    filepath = tmp_path / filename
    filepath.write_text(textwrap.dedent(content))
    return filepath


def test_load_valid_plugin(tmp_path):
    _write_plugin(
        tmp_path,
        "greet.py",
        """
        name = "greeter"
        commands = ["hello", "hi"]
        def handle(text, actor):
            return "hey there"
    """,
    )
    plugins = load_plugins(str(tmp_path))
    assert len(plugins) == 1
    assert plugins[0].name == "greeter"
    assert plugins[0].commands == ["hello", "hi"]
    assert plugins[0].handle("hello", "tom") == "hey there"


def test_skip_malformed_plugin_missing_handle(tmp_path, capsys):
    _write_plugin(
        tmp_path,
        "bad.py",
        """
        name = "bad"
        commands = ["oops"]
    """,
    )
    plugins = load_plugins(str(tmp_path))
    assert len(plugins) == 0
    captured = capsys.readouterr()
    assert "bad.py" in captured.err


def test_skip_malformed_plugin_missing_name(tmp_path, capsys):
    _write_plugin(
        tmp_path,
        "noname.py",
        """
        commands = ["test"]
        def handle(text, actor):
            return "ok"
    """,
    )
    plugins = load_plugins(str(tmp_path))
    assert len(plugins) == 0
    captured = capsys.readouterr()
    assert "noname.py" in captured.err


def test_skip_init_file(tmp_path):
    _write_plugin(tmp_path, "__init__.py", "")
    _write_plugin(
        tmp_path,
        "good.py",
        """
        name = "good"
        commands = ["test"]
        def handle(text, actor):
            return "ok"
    """,
    )
    plugins = load_plugins(str(tmp_path))
    assert len(plugins) == 1
    assert plugins[0].name == "good"


def test_alphabetical_order_by_filename(tmp_path):
    _write_plugin(
        tmp_path,
        "beta.py",
        """
        name = "beta"
        commands = ["b"]
        def handle(text, actor):
            return "beta"
    """,
    )
    _write_plugin(
        tmp_path,
        "alpha.py",
        """
        name = "alpha"
        commands = ["a"]
        def handle(text, actor):
            return "alpha"
    """,
    )
    plugins = load_plugins(str(tmp_path))
    assert [p.name for p in plugins] == ["alpha", "beta"]


def test_skip_non_callable_handle(tmp_path, capsys):
    _write_plugin(
        tmp_path,
        "notcallable.py",
        """
        name = "bad"
        commands = ["test"]
        handle = "not a function"
    """,
    )
    plugins = load_plugins(str(tmp_path))
    assert len(plugins) == 0
    captured = capsys.readouterr()
    assert "notcallable.py" in captured.err


def test_empty_directory(tmp_path):
    plugins = load_plugins(str(tmp_path))
    assert plugins == []


def test_inactive_plugin_skipped(tmp_path):
    _write_plugin(
        tmp_path,
        "myplugin.py",
        """
        name = "myplugin"
        commands = ["do thing"]
        def handle(text, actor):
            return "done"
    """,
    )
    config = {"myplugin": {"active": "no"}}
    plugins = load_plugins(str(tmp_path), config)
    assert len(plugins) == 0


def test_active_plugin_included(tmp_path):
    _write_plugin(
        tmp_path,
        "myplugin.py",
        """
        name = "myplugin"
        commands = ["do thing"]
        def handle(text, actor):
            return "done"
    """,
    )
    config = {"myplugin": {"active": "yes"}}
    plugins = load_plugins(str(tmp_path), config)
    assert len(plugins) == 1


# ---------------------------------------------------------------------------
# Entry-point plugin discovery
# ---------------------------------------------------------------------------


def _make_ep_module(name, commands=None):
    """Build a minimal module that satisfies Sandy's plugin contract."""
    mod = types.ModuleType(name)
    mod.name = name
    mod.commands = commands or [f"{name} go"]
    mod.handle = lambda text, actor: {"title": name, "text": "ok"}
    return mod


def _make_mock_ep(ep_name, module):
    ep = MagicMock()
    ep.name = ep_name
    ep.load.return_value = module
    return ep


def test_entry_point_plugin_loaded(tmp_path, monkeypatch):
    """A valid entry-point plugin is discovered and returned."""
    fake_mod = _make_ep_module("extplugin")
    mock_ep = _make_mock_ep("extplugin", fake_mod)
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points", lambda group=None, **kw: [mock_ep]
    )

    plugins = load_plugins(str(tmp_path))

    assert len(plugins) == 1
    assert plugins[0].name == "extplugin"


def test_entry_point_plugin_merged_with_file_plugins(tmp_path, monkeypatch):
    """File-based and entry-point plugins are both returned."""
    _write_plugin(
        tmp_path,
        "local.py",
        """
        name = "local"
        commands = ["local go"]
        def handle(text, actor):
            return "local"
    """,
    )
    fake_mod = _make_ep_module("extplugin")
    mock_ep = _make_mock_ep("extplugin", fake_mod)
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points", lambda group=None, **kw: [mock_ep]
    )

    plugins = load_plugins(str(tmp_path))

    names = [p.name for p in plugins]
    assert "local" in names
    assert "extplugin" in names


def test_file_plugin_wins_over_entry_point_with_same_name(tmp_path, monkeypatch):
    """When names collide, the file-based plugin takes precedence."""
    _write_plugin(
        tmp_path,
        "myplugin.py",
        """
        name = "myplugin"
        commands = ["myplugin go"]
        def handle(text, actor):
            return {"title": "file", "text": "from file"}
    """,
    )
    ep_mod = _make_ep_module("myplugin")
    ep_mod.handle = lambda text, actor: {"title": "ep", "text": "from entry-point"}
    mock_ep = _make_mock_ep("myplugin", ep_mod)
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points", lambda group=None, **kw: [mock_ep]
    )

    plugins = load_plugins(str(tmp_path))

    assert len(plugins) == 1
    result = plugins[0].handle("myplugin go", "tom")
    assert result["text"] == "from file"


def test_entry_point_plugin_load_error_skipped(tmp_path, monkeypatch, capsys):
    """An entry-point that raises on load is skipped with a warning."""
    broken_ep = MagicMock()
    broken_ep.name = "broken"
    broken_ep.load.side_effect = ImportError("missing dependency")
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points", lambda group=None, **kw: [broken_ep]
    )

    plugins = load_plugins(str(tmp_path))

    assert plugins == []
    assert "broken" in capsys.readouterr().err


def test_entry_point_plugin_missing_attrs_skipped(tmp_path, monkeypatch, capsys):
    """An entry-point module missing required attributes is skipped."""
    bad_mod = types.ModuleType("badplugin")
    bad_mod.name = "badplugin"
    # missing commands and handle
    mock_ep = _make_mock_ep("badplugin", bad_mod)
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points", lambda group=None, **kw: [mock_ep]
    )

    plugins = load_plugins(str(tmp_path))

    assert plugins == []
    assert "badplugin" in capsys.readouterr().err


def test_entry_point_inactive_plugin_skipped(tmp_path, monkeypatch):
    """An entry-point plugin marked inactive in config is skipped."""
    fake_mod = _make_ep_module("myplugin")
    mock_ep = _make_mock_ep("myplugin", fake_mod)
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points", lambda group=None, **kw: [mock_ep]
    )

    config = {"myplugin": {"active": "no"}}
    plugins = load_plugins(str(tmp_path), config)

    assert plugins == []


def test_entry_point_plugins_sorted_by_name(tmp_path, monkeypatch):
    """Multiple entry-point plugins are returned in deterministic name order."""
    mod_b = _make_ep_module("beta")
    mod_a = _make_ep_module("alpha")
    eps = [_make_mock_ep("beta", mod_b), _make_mock_ep("alpha", mod_a)]
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points", lambda group=None, **kw: eps
    )

    plugins = load_plugins(str(tmp_path))

    assert [p.name for p in plugins] == ["alpha", "beta"]


def test_load_plugins_nonexistent_dir(tmp_path, monkeypatch):
    """load_plugins handles a nonexistent plugin_dir without error."""
    plugins = load_plugins(str(tmp_path / "does_not_exist"))
    assert plugins == []


# ---------------------------------------------------------------------------
# Matcher integration — representative plugin command shapes
# ---------------------------------------------------------------------------


def test_real_plugin_command_shapes_match_via_substring(tmp_path, monkeypatch):
    """Plugin commands representative of real packages round-trip through find_matches."""
    representative_commands = [
        # itguy-style commands
        "itguy list",
        "itguy deploy sandy",
        "itguy force recordclub",
        "itguy status",
        "itguy disk",
        # estimatedtaxes-style commands
        "tax summary",
        "tax list",
        "tax sync",
    ]

    class _FakePlugin:
        name = "integration-test"
        commands = representative_commands

        def handle(self, text, actor):
            return {"title": "test", "text": "ok"}

    plugins = [_FakePlugin()]

    for cmd in representative_commands:
        assert find_matches(cmd, plugins), f"Expected '{cmd}' to match"
    assert not find_matches("weather today", plugins)
