"""Core pipeline: match text against plugins, run handlers, collect results.

Also home to the two strings every delivery boundary says about a
pipeline-level outcome -- nothing matched, and a matched plugin raised.
They live beside the conditions they describe; see ``format_plugin_error``
for when that should become a module of its own.
"""

import inspect
import logging
import os
from typing import Callable

from sandy.actors import can_use_plugin, get_owner, resolve_actor, resolve_caps
from sandy.config import apply_env, get_timezone, load_config
from sandy.loader import load_plugins
from sandy.matcher import find_matches
from sandy.observability import capture
from sandy.progress import ProgressFn

logger = logging.getLogger(__name__)

# What every delivery boundary says when nothing matched. Defined here, beside
# the matching it describes, because both boundaries (``cli.main`` and
# ``daemon._handle_callback``) already import from this module and neither owns
# the condition. Deliberately not a personality module: the wording is Tom's to
# pick, and a module named for voice invites agents to add unprompted ones
# (sandy#184). It is the CLI's long-standing line, which README documents and
# CLAUDE.md cites as the house example; the daemon is what changes to meet it.
#
# "Nothing matched" is interaction-level, not answer-level, so by CLAUDE.md's
# boundary rule a plugin must never emit this -- Sandy fans out, and a plugin
# that said it would repeat itself once per non-matching plugin.
NO_MATCH_MESSAGE = "I don't know how to do that yet."

# How much of a failing plugin's exception text a delivery boundary shows.
# Shared rather than the daemon's alone: an unbounded exception string is no
# more welcome in a terminal than on a Slack channel, and a cap on one surface
# only is how the two forked in the first place (#199).
PLUGIN_ERROR_DETAIL_LIMIT = 100

_TRUNCATION_MARKER = "..."


def _truncate(text: str, limit: int) -> str:
    """Cut ``text`` to ``limit`` characters, saying so when anything was lost.

    The marker counts against the limit, so the result is never longer than
    ``limit``. A bare slice is what the daemon did before #199, and it tells
    the reader a lie -- a cut exception is indistinguishable from a whole one,
    which matters most on the long messages where the tail is the informative
    part.

    A *limit* no larger than the marker has no room to say anything was lost,
    so it degrades to a plain cut rather than returning something longer than
    the limit it was given -- which a bare negative slice index would do.
    """
    if len(text) <= limit:
        return text
    if limit <= len(_TRUNCATION_MARKER):
        return text[:limit]
    return text[: limit - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER


def format_plugin_error(plugin_name: str, error_msg: str | None = None) -> str:
    """What every delivery boundary says when a matched plugin raised.

    Lives here rather than in a new ``sandy/messages.py`` (sandy#199 proposed
    one) for two reasons that outlive the taste argument: it sits beside the
    code that *produces* the condition -- ``run_pipeline``'s ``except`` clause
    is what appends the ``(plugin_name, error_message)`` tuple -- and both
    boundaries already import this module, so a new one buys an import edge and
    no behaviour. It is also not purely copy: the cap and the truncation policy
    are pipeline-adjacent decisions, not wording.

    Move both this and ``NO_MATCH_MESSAGE`` to ``sandy/messages.py`` when a
    third shared boundary string appears, or when something that is not the
    pipeline (the printer, a transport) needs one. Until then the split costs
    more than it buys, and it stays a pure rename whenever it is wanted.

    The wording is the daemon's; ``CLAUDE.md`` line 81 cites it as the house
    example of a friendly failure, against ``ERROR: plugin raised RuntimeError``
    as the anti-example. The CLI's old ``<name> plugin failed: <msg>`` was the
    nearer of the two to the anti-example, so the CLI is what moved.

    Returns plain text with no transport markup. The daemon used to wrap the
    detail in backticks, which is Slack mrkdwn baked into a string a terminal
    also prints.

    Routing the detail to the Slack transport's ``code_text`` block instead was
    considered and rejected, on two measurements. ``sandy.plugins.dispatch``
    already decided this question the other way in ``_http_error_message``:
    "errors go into ``text`` (not ``code_text``) so Slack renders them inline".
    And ``format_response`` emits ``code_text`` *before* ``text`` -- pinned
    deliberately by ``test_format_response_code_text_alongside_text`` as "code
    first, then commentary", which is the right order for output-plus-note and
    the wrong one for apology-plus-raw-error: the exception would render above
    the sentence apologising for it.
    """
    friendly = f"I am terribly sorry, {plugin_name} just does not want to behave!"
    if not error_msg:
        return friendly
    return f"{friendly} {_truncate(error_msg, PLUGIN_ERROR_DETAIL_LIMIT)}"


def _default_plugin_dir() -> str:
    return os.path.join(os.path.dirname(__file__), "plugins")


def _accepts_progress(plugin) -> bool:
    """Return True if the plugin's handle() accepts a ``progress`` parameter."""
    try:
        sig = inspect.signature(plugin.handle)
        return "progress" in sig.parameters
    except (TypeError, ValueError):
        return False


def _accepts_tz(plugin) -> bool:
    """Return True if the plugin's handle() accepts a ``tz`` parameter."""
    try:
        sig = inspect.signature(plugin.handle)
        return "tz" in sig.parameters
    except (TypeError, ValueError):
        return False


def _accepts_caps(plugin) -> bool:
    """Return True if the plugin's handle() accepts a ``caps`` parameter."""
    try:
        sig = inspect.signature(plugin.handle)
        return "caps" in sig.parameters
    except (TypeError, ValueError):
        return False


def _build_handler_kwargs(
    plugin,
    reporter,
    effective_tz: str | None,
    actor_caps: frozenset[str],
) -> dict:
    """Build the optional kwargs dict for a plugin's handle() call."""
    kwargs: dict = {}
    if reporter is not None and _accepts_progress(plugin):
        kwargs["progress"] = reporter
    if effective_tz is not None and _accepts_tz(plugin):
        kwargs["tz"] = effective_tz
    if _accepts_caps(plugin):
        kwargs["caps"] = actor_caps
    return kwargs


def run_pipeline(
    text: str,
    actor: str,
    plugin_dir: str | None = None,
    config: dict | None = None,
    plugins: list | None = None,
    progress_factory: Callable[[str], ProgressFn | None] | None = None,
    tz: str | None = None,
) -> tuple[list[tuple[str, object]], list[tuple[str, str]]]:
    """Run the Sandy pipeline: match text, call handlers, collect results.

    Args:
        text: The command text.
        actor: Who sent the command.
        plugin_dir: Directory to load plugins from. Ignored if plugins provided.
        config: Config dict. Loaded from default locations if None.
        plugins: Pre-loaded plugin list. If provided, skips loading.
        progress_factory: Optional callable that takes a plugin name and returns
            a progress reporter (or None to suppress progress).  When provided,
            the reporter is passed to plugins whose ``handle()`` accepts a
            ``progress`` keyword argument.
        tz: IANA timezone name for the requesting user (e.g. ``"America/New_York"``).
            Falls back to ``config["sandy"]["timezone"]`` if not provided.
            Passed to plugins whose ``handle()`` accepts a ``tz`` keyword argument.

    Returns:
        (results, errors) where results is a list of (plugin_name, response)
        and errors is a list of (plugin_name, error_message) tuples.
    """
    if config is None:
        config = load_config()
        apply_env(config)

    # Resolve effective timezone: caller-supplied → config default → None (system TZ)
    effective_tz = tz or get_timezone(config)

    # Actor resolution and permission enforcement
    canonical_actor = resolve_actor(actor, config)
    if canonical_actor is None:
        owner = get_owner(config) or "the owner"
        return [("sandy", {"text": f"I don't know you — please ask {owner} for access."})], []

    actor_caps = resolve_caps(canonical_actor, config)

    if plugins is None:
        if plugin_dir is None:
            plugin_dir = _default_plugin_dir()
        plugins = load_plugins(plugin_dir, config)

    matches = find_matches(text, plugins)
    allowed_matches = [m for m in matches if can_use_plugin(canonical_actor, m.name, config)]
    logger.info(
        "Matched %d plugin(s) for '%s' (actor=%s, allowed=%d): %s",
        len(matches),
        text,
        canonical_actor,
        len(allowed_matches),
        [m.name for m in allowed_matches],
    )

    results = []
    errors = []
    for match in allowed_matches:
        reporter = None
        if progress_factory is not None:
            reporter = progress_factory(match.name)

        try:
            kwargs = _build_handler_kwargs(match, reporter, effective_tz, actor_caps)
            logger.debug(
                "Calling %s.handle(text='%s', actor='%s', kwargs=%s)",
                match.name,
                text,
                actor,
                list(kwargs.keys()),
            )
            response = match.handle(text, actor, **kwargs)
            logger.debug(
                "Plugin '%s' returned: keys=%s",
                match.name,
                list(response.keys()) if isinstance(response, dict) else type(response),
            )
            results.append((match.name, response))
        except Exception as e:
            logger.error("Plugin '%s' failed: %s", match.name, e, exc_info=True)
            capture(e, plugin=match.name)
            errors.append((match.name, str(e)))
        finally:
            if reporter is not None and hasattr(reporter, "clear"):
                reporter.clear()

    return results, errors
