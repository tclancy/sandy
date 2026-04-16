"""Sandy built-in: help.

Shows available commands filtered by the requesting actor's permissions.

Commands:
  "help"     — list commands you have access to
  "health"   — same (backward compat)
"""

from __future__ import annotations

from pathlib import Path

from sandy.actors import can_use_plugin, resolve_actor
from sandy.config import load_config
from sandy.loader import load_plugins

name = "help"
commands = ["help", "health"]


def _plugin_dir() -> Path:
    return Path(__file__).parent


def handle(text: str, actor: str) -> dict:
    """Return a summary of plugins and commands visible to this actor."""
    config = load_config()
    plugins = load_plugins(str(_plugin_dir()), config)
    canonical = resolve_actor(actor, config)

    plugin_summaries: list[str] = []
    for plugin in plugins:
        if not can_use_plugin(canonical, plugin.name, config):
            continue
        plugin_commands = getattr(plugin, "commands", [])
        if plugin_commands:
            cmds = ", ".join(f"`{c}`" for c in plugin_commands)
            plugin_summaries.append(f"• *{plugin.name}*: {cmds}")

    if plugin_summaries:
        lines = ["*Available commands:*"] + plugin_summaries
    else:
        lines = ["No commands available."]

    return {
        "title": "Sandy Help",
        "text": "\n".join(lines),
    }
