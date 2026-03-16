import textwrap
from sandy.loader import load_plugins


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
