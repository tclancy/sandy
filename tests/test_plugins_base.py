"""Tests for the Sandy plugin base class."""

import asyncio

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
