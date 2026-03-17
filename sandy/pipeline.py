"""Core pipeline: match text against plugins, run handlers, collect results."""

import os

from sandy.config import apply_env, load_config
from sandy.loader import load_plugins
from sandy.matcher import find_matches


def _default_plugin_dir() -> str:
    return os.path.join(os.path.dirname(__file__), "plugins")


def run_pipeline(
    text: str,
    actor: str,
    plugin_dir: str | None = None,
    config: dict | None = None,
    plugins: list | None = None,
) -> tuple[list[tuple[str, dict]], list[str]]:
    """Run the Sandy pipeline: match text, call handlers, collect results.

    Args:
        text: The command text.
        actor: Who sent the command.
        plugin_dir: Directory to load plugins from. Ignored if plugins provided.
        config: Config dict. Loaded from default locations if None.
        plugins: Pre-loaded plugin list. If provided, skips loading.

    Returns:
        (results, errors) where results is a list of (plugin_name, response_dict)
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

    results = []
    errors = []
    for match in matches:
        try:
            response = match.handle(text, actor)
            results.append((match.name, response))
        except Exception as e:
            errors.append(f"{match.name} plugin failed: {e}")

    return results, errors
