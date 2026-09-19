"""One condition, one answer: a plugin that raised is reported the same way everywhere.

#187's twin, one branch over. Sandy has two delivery boundaries -- ``cli.main``
for a terminal and ``daemon._handle_callback`` for a transport such as Slack --
and "a plugin raised" is interaction-level output, so by CLAUDE.md's boundary
rule each of them emits it rather than a plugin. That is the shape that drifts,
and it had: the CLI said ``spotify plugin failed: <msg>`` while the daemon said
``I am terribly sorry, spotify just does not want to behave!`` (#199).

As in ``test_no_match_parity.py``, the load-bearing assertion is an equality
between the two *emissions* rather than a substring check against a literal. A
test that pins a literal only catches the wording it was told about; comparing
the surfaces to each other catches any future divergence regardless of what
wording someone picks.

The three cases below are parametrised because the surfaces can agree on the
simple one and still fork on the edges -- an unbounded CLI message against a
capped daemon one was exactly the pre-#199 state, and it is invisible to a test
that only ever raises a short exception.
"""

import asyncio
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

import sandy.config as config_module
import sandy.transports.slack as slack
from sandy.cli import main
from sandy.daemon import Daemon
from sandy.pipeline import PLUGIN_ERROR_DETAIL_LIMIT, _truncate, format_plugin_error

TRIGGER = "break things"

# (id, the exception's str(), what makes it interesting)
ERROR_CASES = [
    pytest.param("Something went wrong: API key missing", id="ordinary-message"),
    pytest.param("", id="no-message"),
    pytest.param("x" * 150, id="over-the-cap"),
]


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch):
    """Keep the real ~/.config/sandy/sandy.toml out of these tests.

    Both helpers drive the production pipeline, which calls ``load_config()``
    and then ``apply_env()`` -- so without this the developer's actual config is
    read and its UPPERCASE keys are injected into ``os.environ`` for every test
    that runs afterwards. It can also turn the run red for an unrelated reason:
    an ``[actors]`` section that does not resolve "tom" makes the pipeline
    return an access-denied *result*, so the error branch never runs at all.
    """
    monkeypatch.setattr(config_module, "_SEARCH_PATHS", [])


def _write_failing_plugin(directory, error_msg):
    """A plugin whose handle() raises RuntimeError(error_msg)."""
    directory.mkdir(parents=True, exist_ok=True)
    # repr() so a 150-char body, an empty string and embedded quotes all survive
    # the trip through the generated source intact.
    (directory / "bad.py").write_text(
        textwrap.dedent(
            f"""
            name = "bad"
            commands = [{TRIGGER!r}]
            def handle(text, actor):
                raise RuntimeError({error_msg!r})
            """
        )
    )
    return str(directory)


def _cli_error_reply(tmp_path, capsys, error_msg):
    """Whatever `sandy break things` writes to stderr when the plugin raises."""
    plugin_dir = _write_failing_plugin(tmp_path / "cli_plugins", error_msg)
    with patch("sandy.pipeline._default_plugin_dir", return_value=plugin_dir):
        exit_code = main([TRIGGER])
    assert exit_code == 1, "every matched plugin failing is a failure exit on the CLI"
    return capsys.readouterr().err.strip()


def _daemon_error_reply(tmp_path, error_msg):
    """Whatever the daemon hands the transport for the same failure."""
    plugin_dir = _write_failing_plugin(tmp_path / "daemon_plugins", error_msg)
    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        replies = []

        async def reply_fn(name, resp):
            replies.append((name, resp))

        await daemon._handle_callback(TRIGGER, "tom", reply_fn)
        assert len(replies) == 1, f"expected exactly one reply, got {replies}"
        return replies[0][1]["text"]

    return asyncio.run(run())


@pytest.mark.parametrize("error_msg", ERROR_CASES)
def test_cli_and_daemon_report_the_same_failure_the_same_way(tmp_path, capsys, error_msg):
    """The defect in #199: same event, different voice, depending on where you typed."""
    cli_reply = _cli_error_reply(tmp_path, capsys, error_msg)
    daemon_reply = _daemon_error_reply(tmp_path, error_msg)

    assert cli_reply == daemon_reply, (
        "the CLI and the daemon reported the same plugin failure differently:\n"
        f"  cli:    {cli_reply!r}\n"
        f"  daemon: {daemon_reply!r}"
    )


@pytest.mark.parametrize("error_msg", ERROR_CASES)
def test_both_surfaces_emit_what_the_shared_formatter_returns(tmp_path, capsys, error_msg):
    """Each boundary's output equals the shared function's, for every case."""
    expected = format_plugin_error("bad", error_msg)
    assert _cli_error_reply(tmp_path, capsys, error_msg) == expected
    assert _daemon_error_reply(tmp_path, error_msg) == expected


@pytest.mark.parametrize("boundary", ["sandy.cli", "sandy.daemon"])
def test_each_boundary_calls_the_shared_formatter_rather_than_matching_it(
    tmp_path, capsys, monkeypatch, boundary
):
    """Agreeing output does not prove a shared *call*, and that is the regression.

    The test above -- and #187's ``test_both_surfaces_emit_the_shared_constant``,
    which has the same defect -- derive ``expected`` by calling the very function
    the boundaries call, so they only re-prove output equality. Measured: replace
    ``daemon.py``'s call with an inline copy producing byte-identical text and the
    whole suite stays green. A re-fork is exactly what this file exists to catch,
    and it survived.

    Patching the name *as each module imported it* is what distinguishes the two.
    Both do ``from sandy.pipeline import format_plugin_error``, so a boundary that
    stops routing through that name stops seeing the sentinel.
    """
    monkeypatch.setattr(
        f"{boundary}.format_plugin_error",
        lambda plugin_name, error_msg=None: f"SENTINEL {plugin_name} {error_msg!r}",
    )
    reply = (
        _cli_error_reply(tmp_path, capsys, "boom")
        if boundary == "sandy.cli"
        else _daemon_error_reply(tmp_path, "boom")
    )
    assert reply == "SENTINEL bad 'boom'", (
        f"{boundary} did not route its plugin-error text through the shared "
        f"sandy.pipeline.format_plugin_error name; it emitted {reply!r}"
    )


def test_the_cap_is_shared_rather_than_the_daemons_alone(tmp_path, capsys):
    """Pre-#199 the daemon capped detail at 100 chars and the CLI capped nothing.

    Parity would be satisfied by *removing* the cap from the daemon as easily as
    by adding it to the CLI, and an unbounded exception string on a Slack channel
    is the worse of the two. Assert the bound holds on the surface that never had
    one, so the cheap direction of the fix cannot pass.
    """
    reply = _cli_error_reply(tmp_path, capsys, "x" * 500)
    headline = format_plugin_error("bad")
    detail = reply[len(headline) :].strip()

    assert detail, "the over-long detail was dropped entirely rather than truncated"
    assert len(detail) == PLUGIN_ERROR_DETAIL_LIMIT, (
        f"CLI detail is {len(detail)} chars, expected the shared "
        f"{PLUGIN_ERROR_DETAIL_LIMIT}-char cap: {detail!r}"
    )


def test_the_shared_cap_is_the_daemons_historical_hundred():
    """Every other cap assertion here derives its expected N from the constant.

    That is the right shape for them -- what they guard is "the surfaces apply
    *the shared* cap", and the constant is the spec. But it means a round of
    them is satisfied by any value at all, so nothing above would notice the
    limit being quietly set to 10 or 10_000. This is the pinned literal beside
    them: 100 is the number the daemon has always used, and changing it is a
    copy decision rather than a refactor.
    """
    assert PLUGIN_ERROR_DETAIL_LIMIT == 100


def test_truncate_never_returns_more_than_the_limit_it_was_given():
    """``_truncate``'s docstring promises a result no longer than ``limit``.

    Unreachable through ``format_plugin_error``, whose only limit is 100 -- but
    ``limit`` is a parameter, and without this the guard against it is a branch
    no test enters: a bare ``text[: limit - 3]`` returns a *negative* slice for
    any limit under 3, so ``_truncate("abcd", 2)`` gives ``"abc..."`` -- six
    characters from a two-character budget, longer than the input. A mutation
    round deleting the guard reported SURVIVED before this existed.
    """
    for limit in range(len("...") + 2):
        result = _truncate("abcdefgh", limit)
        assert len(result) <= limit, (
            f"_truncate(limit={limit}) returned {result!r}, "
            f"{len(result)} chars for a {limit}-char budget"
        )


def test_truncation_is_visible_rather_than_silent():
    """A hard slice tells the reader a lie: it looks like the whole exception.

    The pre-#199 daemon did ``error_msg[:100]`` with no marker, so a truncated
    stack detail was indistinguishable from a complete one -- which matters most
    on exactly the long messages where the tail is the informative part.
    """
    whole = "y" * (PLUGIN_ERROR_DETAIL_LIMIT * 2)
    assert format_plugin_error("bad", whole).endswith("...")
    assert not format_plugin_error("bad", "y" * PLUGIN_ERROR_DETAIL_LIMIT).endswith("...")


def test_no_slack_markup_leaks_into_the_shared_string():
    """The detail used to arrive backtick-wrapped, which the CLI also printed.

    Backticks are Slack mrkdwn, and ``sandy/transports/slack.py`` already owns
    that job -- its ``format_response`` docstring says to prefer a ``code_text``
    block over fences in ``text`` (#122). Markup in a string a terminal also
    prints belongs to the transport, not to the message.
    """
    rendered = format_plugin_error("spotify", "connection refused")
    for markup in ("`", "*", "_", "<", ">"):
        assert markup not in rendered, (
            f"{markup!r} is transport markup and must not appear in the shared "
            f"plugin-error string: {rendered!r}"
        )


def test_readme_documents_the_string_the_code_actually_emits():
    """README described the no-match reply as shared and said nothing about failures.

    Two assertions, because the first would be satisfied by a README that
    quoted the sentence while still implying it is the Slack daemon's alone --
    which was the true state before #199. The second is what fails if the
    "every surface" framing is dropped and the divergence quietly returns.
    """
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    assert "just does not want to behave" in readme, (
        "README.md no longer contains the plugin-failure wording -- "
        "the documented reply has drifted from the code"
    )
    assert "format_plugin_error" in readme, (
        "README.md no longer tells the reader the failure reply is shared "
        "across surfaces -- the split that #199 fixed has come back"
    )


def test_the_house_wording_is_the_daemons_not_the_clis():
    """CLAUDE.md:81 cites this sentence as the house example of a friendly failure.

    It cites ``ERROR: plugin raised RuntimeError`` as the anti-example, and the
    CLI's old ``bad plugin failed: ...`` was much the nearer of the two to it.
    Pinned as a literal deliberately: the parity tests above hold for *any*
    wording both surfaces agree on, including a regression back to the
    anti-example, so something has to name which wording won.
    """
    assert format_plugin_error("spotify") == (
        "I am terribly sorry, spotify just does not want to behave!"
    )


def test_the_daemons_error_payload_renders_as_one_inline_slack_block(tmp_path):
    """Nothing tested what the error reply actually looks like in Slack.

    The daemon's ``reply_fn("error", ...)`` payload never met
    ``format_response`` in any test, so #199 could change the rendering on the
    surface it was meant to improve and no test would say so. Added with the
    decision to keep error detail in ``text``: ``sandy.plugins.dispatch``'s
    ``_http_error_message`` already made that call ("errors go into ``text``
    (not ``code_text``) so Slack renders them inline"), and ``code_text`` would
    put the raw exception *above* the apology -- ``format_response`` emits the
    code block first by design.
    """
    payload = {"text": format_plugin_error("spotify", "connection refused")}
    blocks = slack.format_response("error", payload)["blocks"]

    sections = [b for b in blocks if b.get("type") == "section"]
    assert len(sections) == 1, f"expected one section block, got {blocks}"
    assert sections[0]["text"]["text"] == payload["text"]
    assert not [b for b in blocks if b.get("type") == "rich_text"], (
        "error detail routed to a code block: it would render above the apology"
    )
