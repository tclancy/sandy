"""Core pipeline: match text against plugins, run handlers, collect results."""

import inspect
import logging
import os
from typing import Callable

from sandy.config import apply_env, load_config
from sandy.loader import load_plugins
from sandy.matcher import find_matches
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


def run_pipeline(
    text: str,
    actor: str,
    plugin_dir: str | None = None,
    config: dict | None = None,
    plugins: list | None = None,
    progress_factory: Callable[[str], ProgressFn | None] | None = None,
) -> tuple[list[tuple[str, object]], list[str]]:
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

    Returns:
        (results, errors) where results is a list of (plugin_name, response)
        and errors is a list of error message strings.
    """
    if config is None:
        config = load_config()
        apply_env(config)

    if plugins is None:
        if plugin_dir is None:
            plugin_dir = _default_plugin_dir()
        plugins = load_plugins(plugin_dir, config)

    matches = find_matches(text, plugins)
    logger.info("Matched %d plugin(s) for '%s': %s", len(matches), text, [m.name for m in matches])

    results = []
    errors = []
    for match in matches:
        reporter = None
        if progress_factory is not None:
            reporter = progress_factory(match.name)

        try:
            logger.debug("Calling %s.handle(text='%s', actor='%s')", match.name, text, actor)
            if reporter is not None and _accepts_progress(match):
                response = match.handle(text, actor, progress=reporter)
            else:
                response = match.handle(text, actor)
            logger.debug(
                "Plugin '%s' returned: keys=%s",
                match.name,
                list(response.keys()) if isinstance(response, dict) else type(response),
            )
            results.append((match.name, response))
        except Exception as e:
            logger.error("Plugin '%s' failed: %s", match.name, e, exc_info=True)
            errors.append(f"{match.name} plugin failed: {e}")
        finally:
            if reporter is not None and hasattr(reporter, "clear"):
                reporter.clear()

    return results, errors
