"""Sandy daemon: hosts transport plugins, routes messages through the core pipeline."""

import asyncio
import os
import signal
import sys

from sandy.config import apply_env, load_config
from sandy.loader import load_plugins
from sandy.pipeline import run_pipeline
from sandy.transport_loader import load_transports


class Daemon:
    def __init__(
        self,
        plugin_dir: str | None = None,
        transport_dir: str | None = None,
        config: dict | None = None,
    ):
        if config is None:
            config = load_config()
            apply_env(config)
        self.config = config

        if plugin_dir is None:
            plugin_dir = os.path.join(os.path.dirname(__file__), "plugins")
        if transport_dir is None:
            transport_dir = os.path.join(os.path.dirname(__file__), "transports")

        self.plugins = load_plugins(plugin_dir, config)
        self.transports = load_transports(transport_dir, config)

    async def handle_message(
        self, text: str, actor: str
    ) -> tuple[list[tuple[str, dict]], list[str]]:
        """Run the pipeline in a thread so sync plugins don't block the event loop."""
        return await asyncio.to_thread(
            run_pipeline, text, actor, plugins=self.plugins, config=self.config
        )

    async def run(self):
        """Start all transports and run until interrupted."""
        if not self.transports:
            print("No active transports configured. Nothing to listen on.", file=sys.stderr)
            sys.exit(1)

        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)

        tasks = []
        for transport in self.transports:

            async def callback(text, actor, reply_fn, _transport=transport):
                results, errors = await self.handle_message(text, actor)
                for plugin_name, response in results:
                    await reply_fn(plugin_name, response)
                for error in errors:
                    await reply_fn("error", {"text": error})

            task = asyncio.create_task(transport.listen(callback))
            tasks.append(task)
            print(f"Transport '{transport.name}' started.", file=sys.stderr)

        await stop_event.wait()
        print("\nShutting down...", file=sys.stderr)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def serve():
    """Entry point for `sandy serve`."""
    daemon = Daemon()
    asyncio.run(daemon.run())
