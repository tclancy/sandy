import textwrap
from unittest.mock import patch
from sandy.cli import cli, main


def _make_plugins(tmp_path, plugins):
    """Create plugin files in a temp directory from a dict of {filename: code}."""
    for filename, code in plugins.items():
        (tmp_path / filename).write_text(textwrap.dedent(code))
    return str(tmp_path)


def test_main_routes_to_plugin(tmp_path, capsys):
    plugin_dir = _make_plugins(
        tmp_path,
        {
            "echo.py": """
            name = "echo"
            commands = ["echo"]
            def handle(text, actor):
                return {"text": f"echo: {text} (from {actor})"}
        """
        },
    )
    with patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir):
        exit_code = main(["echo this"])
    captured = capsys.readouterr()
    assert "[echo]" in captured.out
    assert "echo: echo this (from tom)" in captured.out
    assert exit_code == 0


def test_main_fan_out_multiple_matches(tmp_path, capsys):
    plugin_dir = _make_plugins(
        tmp_path,
        {
            "alpha.py": """
            name = "alpha"
            commands = ["summarize"]
            def handle(text, actor):
                return {"text": "alpha summary"}
        """,
            "beta.py": """
            name = "beta"
            commands = ["summarize"]
            def handle(text, actor):
                return {"text": "beta summary"}
        """,
        },
    )
    with patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir):
        exit_code = main(["summarize my day"])
    captured = capsys.readouterr()
    assert "[alpha]" in captured.out
    assert "alpha summary" in captured.out
    assert "[beta]" in captured.out
    assert "beta summary" in captured.out
    assert exit_code == 0


def test_main_no_match(tmp_path, capsys):
    plugin_dir = _make_plugins(
        tmp_path,
        {
            "echo.py": """
            name = "echo"
            commands = ["echo"]
            def handle(text, actor):
                return {"text": "ok"}
        """
        },
    )
    with patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir):
        exit_code = main(["unknown command"])
    captured = capsys.readouterr()
    assert "I don't know how to do that yet." in captured.out
    assert exit_code == 1


def test_main_custom_actor(tmp_path, capsys):
    plugin_dir = _make_plugins(
        tmp_path,
        {
            "echo.py": """
            name = "echo"
            commands = ["echo"]
            def handle(text, actor):
                return {"text": f"echo: {text} (from {actor})"}
        """
        },
    )
    with patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir):
        exit_code = main(["--actor", "michelle", "echo this"])
    captured = capsys.readouterr()
    assert "from michelle" in captured.out
    assert exit_code == 0


def test_main_partial_failure(tmp_path, capsys):
    """One plugin fails, another succeeds — partial success exits 0."""
    plugin_dir = _make_plugins(
        tmp_path,
        {
            "alpha.py": """
            name = "alpha"
            commands = ["test"]
            def handle(text, actor):
                raise RuntimeError("kaboom")
        """,
            "beta.py": """
            name = "beta"
            commands = ["test"]
            def handle(text, actor):
                return {"text": "beta worked"}
        """,
        },
    )
    with patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir):
        exit_code = main(["test"])
    captured = capsys.readouterr()
    assert "alpha plugin failed" in captured.err
    assert "kaboom" in captured.err
    assert "[beta]" in captured.out
    assert "beta worked" in captured.out
    assert exit_code == 0


def test_main_all_matched_plugins_fail(tmp_path, capsys):
    """All matched plugins fail — exits non-zero."""
    _make_plugins(
        tmp_path,
        {
            "boom.py": """
            name = "boom"
            commands = ["boom"]
            def handle(text, actor):
                raise RuntimeError("kaboom")
        """
        },
    )
    with patch("sandy.pipeline._default_plugin_dir", return_value=str(tmp_path)):
        exit_code = main(["boom"])
    captured = capsys.readouterr()
    assert "boom plugin failed" in captured.err
    assert exit_code == 1


def test_main_no_args(capsys):
    exit_code = main([])
    assert exit_code == 1


def test_cli_keyboard_interrupt(capsys):
    """CTRL-C during execution exits cleanly with a friendly message."""
    import pytest

    with patch("sandy.cli.main", side_effect=KeyboardInterrupt):
        with pytest.raises(SystemExit) as exc_info:
            cli()
    captured = capsys.readouterr()
    assert "Wrapping up early today!" in captured.out
    assert exc_info.value.code == 0
