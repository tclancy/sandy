"""Sandy built-in: help.

Shows available commands filtered by the requesting actor's permissions.

Commands:
  "help"     — list commands you have access to

Uses ``match_mode = "prefix"`` so ``help`` only fires when it's the leading
intent, not when it appears mid-sentence like ``itguy logs --help`` (#139).
The ``health`` alias was retired in the same change.
"""

from __future__ import annotations

from pathlib import Path

from sandy.actors import can_use_plugin, resolve_actor
from sandy.config import load_config
from sandy.loader import load_plugins

name = "help"
commands = ["help"]
match_mode = "prefix"


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
        # A plugin can declare compound commands (ones that need a subcommand,
        # like "itguy arr <sub>") in ``command_groups``. Sandy hoists each group
        # onto its own row so the subcommands are actually documented, instead
        # of `itguy arr` showing up as a leaf next to non-compound siblings
        # (itguy#131). The group key is de-duped out of the flat row so plugins
        # can keep the compound in ``commands`` for back-compat with older
        # Sandys that don't read ``command_groups``.
        command_groups = getattr(plugin, "command_groups", {}) or {}
        top_level = [c for c in plugin_commands if c not in command_groups]
        if top_level:
            cmds = ", ".join(f"`{c}`" for c in top_level)
            plugin_summaries.append(f"• *{plugin.name}*: {cmds}")
        for group_name, group_cmds in command_groups.items():
            if group_cmds:
                cmds = ", ".join(f"`{c}`" for c in group_cmds)
                plugin_summaries.append(f"• *{group_name}*: {cmds}")

    if plugin_summaries:
        lines = ["*Available commands:*"] + plugin_summaries
    else:
        lines = ["No commands available."]

    return {
        "title": "Sandy Help",
        "text": "\n".join(lines),
    }
