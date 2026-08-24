import textwrap
from unittest.mock import patch

import pytest

import sandy.config as config_module
from sandy.cli import (
    _format_audio,
    _format_links,
    _format_text,
    _format_title,
    _render_response,
    cli,
    main,
)


# --- field formatter unit tests ---


def test_format_title_returns_value_in_list():
    assert _format_title("My Title") == ["My Title"]


def test_format_text_returns_value_in_list():
    assert _format_text("Hello world") == ["Hello world"]


def test_format_audio_plays_and_returns_empty(tmp_path):
    with (
        patch("sandy.cli.requests.get") as mock_get,
        patch("sandy.cli.subprocess.run") as mock_run,
    ):
        resp = mock_get.return_value
        resp.content = b"fake-mp3"
        resp.raise_for_status = lambda: None
        result = _format_audio("https://example.com/test.mp3")
    assert result == []
    mock_run.assert_called_once()


def test_format_audio_returns_fallback_on_error():
    with patch("sandy.cli.requests.get", side_effect=Exception("network error")):
        result = _format_audio("https://example.com/test.mp3")
    assert len(result) == 1
    assert "could not play audio" in result[0]


def test_render_response_audio_url():
    """audio_url is handled by the formatter (playback mocked)."""
    with (
        patch("sandy.cli.requests.get") as mock_get,
        patch("sandy.cli.subprocess.run"),
    ):
        mock_get.return_value.content = b"fake"
        mock_get.return_value.raise_for_status = lambda: None
        out = _render_response("real_men", {"text": "Genius", "audio_url": "http://x.com/a.mp3"})
    assert "[real_men]" in out
    assert "Genius" in out


def test_format_links_formats_each_link():
    links = [
        {"label": "Spotify", "url": "https://open.spotify.com/album/abc"},
        {"label": "Apple Music", "url": "https://music.apple.com/album/abc"},
    ]
    result = _format_links(links)
    assert result == [
        "  Spotify: https://open.spotify.com/album/abc",
        "  Apple Music: https://music.apple.com/album/abc",
    ]


def test_render_response_title_only():
    out = _render_response("myplugin", {"title": "A Title"})
    assert out == "[myplugin]\nA Title"


def test_render_response_text_only():
    out = _render_response("myplugin", {"text": "Some text"})
    assert out == "[myplugin]\nSome text"


def test_render_response_links_only():
    out = _render_response("myplugin", {"links": [{"label": "X", "url": "http://x.com"}]})
    assert out == "[myplugin]\n  X: http://x.com"


def test_render_response_all_fields():
    out = _render_response(
        "myplugin",
        {
            "title": "Headlines",
            "text": "Body text here.",
            "links": [{"label": "Read more", "url": "http://example.com"}],
        },
    )
    assert out == "[myplugin]\nHeadlines\nBody text here.\n  Read more: http://example.com"


def test_render_response_unknown_keys_skipped():
    out = _render_response("myplugin", {"text": "hi", "future_field": "ignored"})
    assert out == "[myplugin]\nhi"


# --- integration tests ---


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
    with (
        patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir),
        patch("sandy.cli.voice.opening_aside", return_value=None),
    ):
        exit_code = main(["unknown command"])
    captured = capsys.readouterr()
    assert "unknown command" in captured.out
    assert "help" in captured.out
    assert exit_code == 1


def test_main_custom_actor(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(config_module, "_SEARCH_PATHS", [])
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


# --- timezone flag ---


def test_main_timezone_flag_passed_to_pipeline(tmp_path, capsys):
    """--timezone is forwarded to run_pipeline as the tz kwarg."""
    plugin_dir = _make_plugins(
        tmp_path,
        {
            "tz_echo.py": """
            name = "tz_echo"
            commands = ["tz test"]
            def handle(text, actor, tz=None):
                return {"text": f"tz={tz}"}
        """
        },
    )
    with patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir):
        exit_code = main(["--timezone", "America/Chicago", "tz test"])
    captured = capsys.readouterr()
    assert "tz=America/Chicago" in captured.out
    assert exit_code == 0


def test_main_timezone_short_flag(tmp_path, capsys):
    """Short flag -z is an alias for --timezone."""
    plugin_dir = _make_plugins(
        tmp_path,
        {
            "tz_echo.py": """
            name = "tz_echo"
            commands = ["tz test"]
            def handle(text, actor, tz=None):
                return {"text": f"tz={tz}"}
        """
        },
    )
    with patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir):
        exit_code = main(["-z", "Europe/London", "tz test"])
    captured = capsys.readouterr()
    assert "tz=Europe/London" in captured.out
    assert exit_code == 0


def test_main_timezone_default_is_none(tmp_path, capsys, monkeypatch):
    """Without --timezone and no config, tz defaults to None."""
    monkeypatch.setattr(config_module, "_SEARCH_PATHS", [])
    plugin_dir = _make_plugins(
        tmp_path,
        {
            "tz_echo.py": """
            name = "tz_echo"
            commands = ["tz test"]
            def handle(text, actor, tz=None):
                return {"text": f"tz={tz}"}
        """
        },
    )
    with patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir):
        exit_code = main(["tz test"])
    captured = capsys.readouterr()
    assert "tz=None" in captured.out
    assert exit_code == 0


# --- voice: one aside per interaction, at the delivery boundary (sandy#183) ---


def test_main_opens_with_the_aside_above_the_first_answer(tmp_path, capsys):
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
    with (
        patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir),
        patch("sandy.cli.voice.opening_aside", return_value="Wow, you're up late, Tom."),
    ):
        exit_code = main(["echo this"])
    out = capsys.readouterr().out
    assert out.index("Wow, you're up late, Tom.") < out.index("ok")
    assert exit_code == 0


def test_main_says_the_aside_once_even_when_several_plugins_answer(tmp_path, capsys):
    """Sandy fans out — an aside per response would repeat it once per match."""
    plugin_dir = _make_plugins(
        tmp_path,
        {
            "alpha.py": """
            name = "alpha"
            commands = ["test"]
            def handle(text, actor):
                return {"text": "alpha answer"}
        """,
            "beta.py": """
            name = "beta"
            commands = ["test"]
            def handle(text, actor):
                return {"text": "beta answer"}
        """,
        },
    )
    with (
        patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir),
        patch("sandy.cli.voice.opening_aside", return_value="You're up early, Tom."),
    ):
        main(["test"])
    out = capsys.readouterr().out
    assert out.count("You're up early, Tom.") == 1
    assert "alpha answer" in out
    assert "beta answer" in out


def test_main_stays_quiet_when_the_hour_is_unremarkable(tmp_path, capsys):
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
    with (
        patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir),
        patch("sandy.cli.voice.opening_aside", return_value=None),
    ):
        main(["echo this"])
    out = capsys.readouterr().out
    assert out.strip().splitlines()[0] == "[echo]"


def test_main_carries_the_aside_on_the_unmatched_reply_too(tmp_path, capsys):
    """Nothing matched is still an interaction — 3am is 3am either way."""
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
    with (
        patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir),
        patch("sandy.cli.voice.opening_aside", return_value="Wow, you're up late, Tom."),
    ):
        exit_code = main(["wibble the frobnitz"])
    out = capsys.readouterr().out
    assert "Wow, you're up late, Tom." in out
    assert "wibble the frobnitz" in out
    assert exit_code == 1


def test_main_passes_the_requested_timezone_to_the_voice(tmp_path):
    """3am is only remarkable where the user is."""
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
    with (
        patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir),
        patch("sandy.cli.voice.opening_aside", return_value=None) as spy,
    ):
        main(["--actor", "michelle", "--timezone", "Europe/London", "echo this"])
    assert spy.call_args.args[0] == "michelle"
    assert spy.call_args.kwargs["tz"] == "Europe/London"


def test_main_opens_with_the_aside_above_the_plugin_s_own_title(tmp_path, capsys):
    """A greeting under the header reads like a footnote (sandy#183)."""
    plugin_dir = _make_plugins(
        tmp_path,
        {
            "titled.py": """
            name = "titled"
            commands = ["titled"]
            def handle(text, actor):
                return {"title": "Sandy Help", "text": "the body"}
        """
        },
    )
    with (
        patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir),
        patch("sandy.cli.voice.opening_aside", return_value="Wow, you're up late, Tom."),
    ):
        main(["titled"])
    out = capsys.readouterr().out
    assert out.index("Wow, you're up late, Tom.") < out.index("Sandy Help")


def _echo_plugin_dir(tmp_path):
    return _make_plugins(
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


def _write_config(tmp_path, body: str, monkeypatch):
    path = tmp_path / "sandy.toml"
    path.write_text(textwrap.dedent(body))
    monkeypatch.setattr(config_module, "_SEARCH_PATHS", [path])
    return path


@pytest.mark.real_voice
def test_main_honours_the_flourishes_kill_switch(tmp_path, capsys, monkeypatch):
    """`[sandy] flourishes = "no"` has to reach the voice, not just exist.

    Patches the inner clock-reading function, so `opening_aside`'s own config
    handling runs for real — deleting `config=config` from `cli.main` turns
    this red (sandy#183 review found nothing held that argument in place).
    """
    plugin_dir = _echo_plugin_dir(tmp_path)
    _write_config(tmp_path, '[sandy]\nflourishes = "no"\n', monkeypatch)

    with (
        patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir),
        patch("sandy.voice.time_of_day_aside", return_value="Wow, you're up late, Tom."),
    ):
        main(["echo this"])

    assert "up late" not in capsys.readouterr().out


@pytest.mark.real_voice
def test_main_speaks_when_the_kill_switch_is_off(tmp_path, capsys, monkeypatch):
    """Positive control for the test above — same setup, switch the other way."""
    plugin_dir = _echo_plugin_dir(tmp_path)
    _write_config(tmp_path, '[sandy]\nflourishes = "yes"\n', monkeypatch)

    with (
        patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir),
        patch("sandy.voice.time_of_day_aside", return_value="Wow, you're up late, Tom."),
    ):
        main(["echo this"])

    assert "up late" in capsys.readouterr().out
