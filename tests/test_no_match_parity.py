"""One condition, one answer: the no-match reply is the same on every surface.

Sandy has two delivery boundaries -- ``cli.main`` for a terminal and
``daemon._handle_callback`` for a transport such as Slack. "Nothing matched"
is interaction-level output, so by CLAUDE.md's boundary rule it is emitted by
each of them rather than by a plugin. That is exactly the shape that drifts:
the two lines diverged for months and nothing failed (#187).

The parity test below is deliberately written as an equality between the two
*emissions* rather than as a substring check against a literal. A test that
pins a literal only catches the wording it was told about -- rename the string
on both sides and it keeps passing while the invariant it claims to guard is
untested. Comparing the surfaces to each other catches any future divergence
regardless of what wording someone picks.
"""

import asyncio
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

import sandy.config as config_module
from sandy.cli import main
from sandy.daemon import Daemon
from sandy.pipeline import NO_MATCH_MESSAGE

UNMATCHED = "something no plugin has ever heard of"


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch):
    """Keep the real ~/.config/sandy/sandy.toml out of these tests.

    Both helpers drive the production pipeline, which calls ``load_config()``
    and then ``apply_env()`` -- so without this the developer's actual config is
    read and its UPPERCASE keys (Slack and Spotify tokens among them) are
    injected into ``os.environ`` for every test that runs afterwards. It can
    also turn the run red for an unrelated reason: an ``[actors]`` section that
    does not resolve "tom" makes the pipeline return an access-denied *result*,
    so the no-match branch never runs at all.
    """
    monkeypatch.setattr(config_module, "_SEARCH_PATHS", [])


_ECHO_PLUGIN = {
    "echo.py": """
    name = "echo"
    commands = ["echo"]
    def handle(text, actor):
        return {"text": "ok"}
"""
}


def _write_plugins(directory, plugins):
    directory.mkdir(parents=True, exist_ok=True)
    for filename, code in plugins.items():
        (directory / filename).write_text(textwrap.dedent(code))
    return str(directory)


def _cli_no_match_reply(tmp_path, capsys):
    """Whatever `sandy <unmatched text>` prints to stdout."""
    plugin_dir = _write_plugins(tmp_path / "cli_plugins", _ECHO_PLUGIN)
    with patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir):
        exit_code = main([UNMATCHED])
    assert exit_code == 1, "a no-match is a failure exit on the CLI"
    return capsys.readouterr().out.strip()


def _daemon_no_match_reply(tmp_path):
    """Whatever the daemon hands the transport for the same unmatched text."""
    plugin_dir = _write_plugins(tmp_path / "daemon_plugins", _ECHO_PLUGIN)
    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        replies = []

        async def reply_fn(name, resp):
            replies.append((name, resp))

        await daemon._handle_callback(UNMATCHED, "tom", reply_fn)
        assert len(replies) == 1, f"expected exactly one reply, got {replies}"
        return replies[0][1]["text"]

    return asyncio.run(run())


def test_cli_and_daemon_give_the_same_answer_to_the_same_no_match(tmp_path, capsys):
    """The defect in #187: same event, different voice, depending on where you typed."""
    cli_reply = _cli_no_match_reply(tmp_path, capsys)
    daemon_reply = _daemon_no_match_reply(tmp_path)

    assert cli_reply == daemon_reply, (
        "the CLI and the daemon answered the same no-match differently:\n"
        f"  cli:    {cli_reply!r}\n"
        f"  daemon: {daemon_reply!r}"
    )


def test_both_surfaces_emit_the_shared_constant(tmp_path, capsys):
    """Each boundary's reply equals the shared constant's value."""
    assert _cli_no_match_reply(tmp_path, capsys) == NO_MATCH_MESSAGE
    assert _daemon_no_match_reply(tmp_path) == NO_MATCH_MESSAGE


@pytest.mark.parametrize("boundary", ["sandy.cli", "sandy.daemon"])
def test_each_boundary_reads_the_shared_constant_rather_than_matching_it(
    tmp_path, capsys, monkeypatch, boundary
):
    """Equal values do not prove a shared *read*, and the re-fork is the regression.

    The test above compares each surface against ``NO_MATCH_MESSAGE``, so a call
    site that went back to its own literal spelled the same way passes it. That
    is precisely the state #187 fixed, and nothing here could detect its return.
    Added with #199, whose parity file had inherited the identical overclaim.

    Both boundaries do ``from sandy.pipeline import NO_MATCH_MESSAGE``, so
    patching the name as each module imported it is what tells "reads the shared
    definition" apart from "happens to agree with it".
    """
    monkeypatch.setattr(f"{boundary}.NO_MATCH_MESSAGE", "SENTINEL no-match reply")
    reply = (
        _cli_no_match_reply(tmp_path, capsys)
        if boundary == "sandy.cli"
        else _daemon_no_match_reply(tmp_path)
    )
    assert reply == "SENTINEL no-match reply", (
        f"{boundary} did not read sandy.pipeline.NO_MATCH_MESSAGE for its "
        f"no-match reply; it emitted {reply!r}"
    )


def test_readme_documents_the_string_the_code_actually_emits():
    """README told users about the CLI wording; it is now true of Slack too.

    Two assertions, because the first one alone was already green on
    ``origin/main`` -- README has quoted the CLI's line for as long as it has
    existed. Only the second is evidence about *this* change, and it is what
    fails if the "every surface" sentence is dropped while the divergence is
    quietly reintroduced.
    """
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    assert NO_MATCH_MESSAGE in readme, (
        f"README.md does not contain {NO_MATCH_MESSAGE!r} -- "
        "the documented no-match reply has drifted from the code"
    )
    assert "NO_MATCH_MESSAGE" in readme, (
        "README.md no longer tells the reader the reply is shared across "
        "surfaces -- the CLI-only framing that #187 fixed has come back"
    )
