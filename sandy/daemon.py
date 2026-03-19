"""Sandy daemon: hosts transport plugins, routes messages through the core pipeline."""

import asyncio
import logging
import os
import signal
import sys

from sandy.config import apply_env, load_config
from sandy.loader import load_plugins
from sandy.pipeline import run_pipeline
from sandy.transport_loader import load_transports

logger = logging.getLogger(__name__)


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
        logger.info(
            "Loaded %d content plugin(s): %s", len(self.plugins), [p.name for p in self.plugins]
        )
        self.transports = load_transports(transport_dir, config)
        logger.info(
            "Loaded %d transport(s): %s", len(self.transports), [t.name for t in self.transports]
        )

    async def handle_message(
        self, text: str, actor: str
    ) -> tuple[list[tuple[str, dict]], list[str]]:
        """Run the pipeline in a thread so sync plugins don't block the event loop."""
        logger.debug("Routing message to pipeline: text='%s', actor='%s'", text, actor)
        results, errors = await asyncio.to_thread(
            run_pipeline, text, actor, plugins=self.plugins, config=self.config
        )
        logger.info("Pipeline returned %d result(s), %d error(s)", len(results), len(errors))
        if errors:
            logger.warning("Pipeline errors: %s", errors)
        return results, errors

    async def run(self):
        """Start all transports and run until interrupted."""
        if not self.transports:
            logger.error("No active transports configured. Nothing to listen on.")
            sys.exit(1)

        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)

        tasks = []
        for transport in self.transports:

            async def callback(text, actor, reply_fn):
                logger.debug("Callback invoked: text='%s', actor='%s'", text, actor)
                results, errors = await self.handle_message(text, actor)
                for plugin_name, response in results:
                    logger.debug("Dispatching reply for '%s' back to transport", plugin_name)
                    await reply_fn(plugin_name, response)
                for error in errors:
                    logger.debug("Dispatching error reply: %s", error)
                    await reply_fn("error", {"text": error})

            task = asyncio.create_task(transport.listen(callback))
            tasks.append(task)
            logger.info("Transport '%s' started", transport.name)

        await stop_event.wait()
        logger.info("Shutting down...")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _configure_logging(config: dict) -> None:
    """Set up logging from the [daemon] config section.

    Reads ``log_level`` from ``[daemon]`` (default: ``INFO``).
    """
    daemon_config = config.get("daemon", {})
    level_name = daemon_config.get("log_level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.debug("Logging configured at %s level", level_name)


def serve():
    """Entry point for `sandy serve`."""
    config = load_config()
    apply_env(config)
    _configure_logging(config)
    daemon = Daemon(config=config)
    asyncio.run(daemon.run())
