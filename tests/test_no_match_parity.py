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
from unittest.mock import patch

from sandy.cli import main
from sandy.daemon import Daemon
from sandy.pipeline import NO_MATCH_MESSAGE

UNMATCHED = "something no plugin has ever heard of"

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
    """Parity alone is satisfiable by two literals that happen to agree today.

    This pins that the agreement comes from the single shared definition, so
    editing one call site cannot quietly re-fork it while parity still holds.
    """
    assert _cli_no_match_reply(tmp_path, capsys) == NO_MATCH_MESSAGE
    assert _daemon_no_match_reply(tmp_path) == NO_MATCH_MESSAGE


def test_readme_documents_the_string_the_code_actually_emits():
    """README told users about the CLI wording; it is now true of Slack too."""
    from pathlib import Path

    readme = Path(__file__).resolve().parent.parent / "README.md"
    assert NO_MATCH_MESSAGE in readme.read_text(), (
        f"README.md does not contain {NO_MATCH_MESSAGE!r} -- "
        "the documented no-match reply has drifted from the code"
    )
