"""Optional base class for Sandy content plugins.

Module-level plugins (name, commands, handle at module scope) continue to work
unchanged. Class-based plugins can subclass SandyPlugin and override
``handle_async`` for true async execution without the ``asyncio.to_thread``
wrapper.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from sandy.progress import ProgressFn


class SandyPlugin(ABC):
    """Base class for Sandy content plugins.

    Subclass this and override ``handle()`` (sync) or ``handle_async()``
    (async) to write a plugin. If only ``handle()`` is overridden, a default
    ``handle_async()`` wraps it in ``asyncio.to_thread`` automatically — no
    plugin migration needed.

    **If the plugin is a file in the plugin directory, subclassing is not
    enough.** That loader reads module scope and appends the *module*, so
    bridge the instance out beneath the class::

        plugin = MyPlugin()
        name = plugin.name
        commands = plugin.commands
        handle = plugin.handle

    A subclass without the bridge is skipped with a warning naming these lines
    (#182). Entry-point plugins register the object directly and need no bridge.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin identifier shown in responses."""

    @property
    @abstractmethod
    def commands(self) -> list[str]:
        """Substrings that trigger this plugin."""

    @abstractmethod
    def handle(self, text: str, actor: str, progress: ProgressFn | None = None) -> dict:
        """Process the command and return a response dict."""

    async def handle_async(self, text: str, actor: str, progress: ProgressFn | None = None) -> dict:
        """Async version of handle(). Default: run handle() in a thread.

        Override this method to avoid the thread overhead for fully
        async plugins.
        """
        return await asyncio.to_thread(self.handle, text, actor, progress=progress)
