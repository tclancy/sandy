"""Core pipeline: match text against plugins, run handlers, collect results."""

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
