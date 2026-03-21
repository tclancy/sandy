"""Progress reporting for Sandy plugins.

Plugins can optionally accept a ``progress`` callable as a third argument to
``handle()``.  When present, calling it emits a status message to the user
while the plugin is working.  Existing plugins that do not accept ``progress``
continue to work unchanged.

Usage inside a plugin::

    def handle(text: str, actor: str, progress=None) -> dict:
        if progress:
            progress("Fetching artist list…")
        artists = _get_followed_artists(sp)
        for i, artist in enumerate(artists):
            if progress:
                progress(f"Checking {artist['name']} ({i + 1}/{len(artists)})")
            ...

The CLI passes a :class:`CliProgressReporter` that writes to stderr so stdout
remains clean for piping.  Daemon transports may pass their own reporter or
``None`` to suppress output.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Callable


ProgressFn = Callable[[str], None]


class CliProgressReporter:
    """Writes progress messages to stderr, overwriting the previous line.

    Each message replaces the previous one on the terminal so the screen stays
    tidy.  Call :meth:`clear` to erase the last message when the plugin is
    done (the pipeline does this automatically).
    """

    _PAD = 60  # spaces used to overwrite a previous longer message

    def __init__(self, plugin_name: str, file=None) -> None:
        self._plugin_name = plugin_name
        self._file = file or sys.stderr
        self._active = False

    def __call__(self, message: str) -> None:
        line = f"  [{self._plugin_name}] {message}"
        # Truncate long messages to avoid wrapping, then pad to erase leftovers
        display = line[: self._PAD].ljust(self._PAD)
        self._file.write(f"\r{display}")
        self._file.flush()
        self._active = True

    def clear(self) -> None:
        """Erase the progress line once the plugin finishes."""
        if self._active:
            self._file.write("\r" + " " * self._PAD + "\r")
            self._file.flush()
            self._active = False


class QueueProgressReporter:
    """Thread-safe progress reporter for daemon transports.

    Pushes messages onto an asyncio.Queue via call_soon_threadsafe so it
    can be called from a worker thread while the event loop drains messages.
    """

    def __init__(
        self,
        plugin_name: str,
        queue: asyncio.Queue[str | None],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._plugin_name = plugin_name
        self._queue = queue
        self._loop = loop

    def __call__(self, message: str) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, f"[{self._plugin_name}] {message}")

    def clear(self) -> None:
        pass  # Daemon signals termination with a None sentinel; no-op here


def make_reporter(plugin_name: str) -> CliProgressReporter:
    """Return a :class:`CliProgressReporter` for the given plugin."""
    return CliProgressReporter(plugin_name)
