"""Sandy built-in: health check.

Reports Sandy's runtime status — loaded plugins and their commands.

Commands:
  "health"   — list all active plugins and the commands each handles
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from sandy.config import is_active, load_config

name = "health"
commands = ["health"]


def _plugin_dir() -> Path:
    return Path(__file__).parent


def handle(text: str, actor: str) -> dict:
    """Return a summary of all loaded plugins and their commands."""
    plugin_dir = _plugin_dir()
    config = load_config()

    filenames = sorted(
        f for f in os.listdir(plugin_dir) if f.endswith(".py") and f != "__init__.py"
    )

    plugin_summaries: list[str] = []
    for filename in filenames:
        filepath = plugin_dir / filename
        try:
            module_name = f"_health_inspect_{filename}"
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            plugin_name = getattr(module, "name", filename.removesuffix(".py"))
            if not is_active(config, plugin_name):
                continue
            plugin_commands = getattr(module, "commands", [])
            if plugin_commands:
                cmds = ", ".join(f"`{c}`" for c in plugin_commands)
                plugin_summaries.append(f"• *{plugin_name}*: {cmds}")
        except Exception:
            continue

    if plugin_summaries:
        lines = ["*Active plugins:*"] + plugin_summaries
    else:
        lines = ["No plugins found."]

    return {
        "title": "Sandy Health",
        "text": "\n".join(lines),
    }
