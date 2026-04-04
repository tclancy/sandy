import textwrap
import types
from unittest.mock import MagicMock, patch

import pytest

from sandy.loader import load_plugins


@pytest.fixture(autouse=True)
def no_entry_points(monkeypatch):
    """Suppress real entry-point discovery in all loader tests by default.

    Tests that specifically exercise entry-point loading use their own
    ``with patch(...)`` block which overrides this fixture for that scope.
    """
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points",
        lambda **kwargs: [],
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


def test_entry_point_plugin_loaded(tmp_path):
    """A valid entry-point plugin is discovered and returned."""
    fake_mod = _make_ep_module("extplugin")
    mock_ep = _make_mock_ep("extplugin", fake_mod)

    with patch("sandy.loader.importlib.metadata.entry_points", return_value=[mock_ep]):
        plugins = load_plugins(str(tmp_path))

    assert len(plugins) == 1
    assert plugins[0].name == "extplugin"


def test_entry_point_plugin_merged_with_file_plugins(tmp_path):
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

    with patch("sandy.loader.importlib.metadata.entry_points", return_value=[mock_ep]):
        plugins = load_plugins(str(tmp_path))

    names = [p.name for p in plugins]
    assert "local" in names
    assert "extplugin" in names


def test_file_plugin_wins_over_entry_point_with_same_name(tmp_path):
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

    with patch("sandy.loader.importlib.metadata.entry_points", return_value=[mock_ep]):
        plugins = load_plugins(str(tmp_path))

    assert len(plugins) == 1
    result = plugins[0].handle("myplugin go", "tom")
    assert result["text"] == "from file"


def test_entry_point_plugin_load_error_skipped(tmp_path, capsys):
    """An entry-point that raises on load is skipped with a warning."""
    broken_ep = MagicMock()
    broken_ep.name = "broken"
    broken_ep.load.side_effect = ImportError("missing dependency")

    with patch("sandy.loader.importlib.metadata.entry_points", return_value=[broken_ep]):
        plugins = load_plugins(str(tmp_path))

    assert plugins == []
    assert "broken" in capsys.readouterr().err


def test_entry_point_plugin_missing_attrs_skipped(tmp_path, capsys):
    """An entry-point module missing required attributes is skipped."""
    bad_mod = types.ModuleType("badplugin")
    bad_mod.name = "badplugin"
    # missing commands and handle
    mock_ep = _make_mock_ep("badplugin", bad_mod)

    with patch("sandy.loader.importlib.metadata.entry_points", return_value=[mock_ep]):
        plugins = load_plugins(str(tmp_path))

    assert plugins == []
    assert "badplugin" in capsys.readouterr().err


def test_entry_point_inactive_plugin_skipped(tmp_path):
    """An entry-point plugin marked inactive in config is skipped."""
    fake_mod = _make_ep_module("myplugin")
    mock_ep = _make_mock_ep("myplugin", fake_mod)

    config = {"myplugin": {"active": "no"}}
    with patch("sandy.loader.importlib.metadata.entry_points", return_value=[mock_ep]):
        plugins = load_plugins(str(tmp_path), config)

    assert plugins == []
