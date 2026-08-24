"""Tests for the Sandy plugin base class."""

import asyncio
from pathlib import Path

from sandy.plugins.base import SandyPlugin


def test_sandy_plugin_handle_async_default():
    """Default handle_async wraps sync handle via to_thread."""

    class EchoPlugin(SandyPlugin):
        @property
        def name(self):
            return "echo"

        @property
        def commands(self):
            return ["echo"]

        def handle(self, text, actor, progress=None):
            return {"text": f"echo: {text}"}

    plugin = EchoPlugin()

    async def run():
        result = await plugin.handle_async("echo hello", "tom")
        assert result == {"text": "echo: echo hello"}

    asyncio.run(run())


def test_no_plugin_imports_the_voice():
    """Sandy fans out, so an aside emitted from a plugin repeats once per match.

    CLAUDE.md states the rule; this is what keeps it true. Asides belong to the
    interaction and are attached at the delivery boundary (`cli.main`,
    `daemon._deliver`).
    """
    plugin_dir = Path(__file__).resolve().parent.parent / "sandy" / "plugins"
    offenders = [
        path.name
        for path in sorted(plugin_dir.glob("*.py"))
        if "sandy.voice" in path.read_text() or "from sandy import voice" in path.read_text()
    ]

    assert offenders == []
