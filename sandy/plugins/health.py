"""Sandy built-in: health check.

Reports Sandy's runtime status — loaded plugins and their commands.

Commands:
  "health"   — list all active plugins and the commands each handles
"""

from __future__ import annotations

from pathlib import Path

from sandy.config import load_config
from sandy.loader import load_plugins

name = "health"
commands = ["health"]


def _plugin_dir() -> Path:
    return Path(__file__).parent


def handle(text: str, actor: str) -> dict:
    """Return a summary of all loaded plugins and their commands."""
    config = load_config()
    plugins = load_plugins(str(_plugin_dir()), config)

    plugin_summaries: list[str] = []
    for plugin in plugins:
        plugin_commands = getattr(plugin, "commands", [])
        if plugin_commands:
            cmds = ", ".join(f"`{c}`" for c in plugin_commands)
            plugin_summaries.append(f"• *{plugin.name}*: {cmds}")

    if plugin_summaries:
        lines = ["*Active plugins:*"] + plugin_summaries
    else:
        lines = ["No plugins found."]

    return {
        "title": "Sandy Health",
        "text": "\n".join(lines),
    }
