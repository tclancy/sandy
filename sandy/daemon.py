"""Sandy daemon: hosts transport plugins, routes messages through the core pipeline."""

import asyncio
import logging
import os
import signal
import sys

from sandy.config import apply_env, load_config
from sandy.loader import load_plugins
from sandy.pipeline import run_pipeline
from sandy.progress import QueueProgressReporter
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
        self, text: str, actor: str, progress_factory=None
    ) -> tuple[list[tuple[str, dict]], list[tuple[str, str]]]:
        """Run the pipeline in a thread so sync plugins don't block the event loop."""
        logger.debug("Routing message to pipeline: text='%s', actor='%s'", text, actor)
        results, errors = await asyncio.to_thread(
            run_pipeline,
            text,
            actor,
            plugins=self.plugins,
            config=self.config,
            progress_factory=progress_factory,
        )
        logger.info("Pipeline returned %d result(s), %d error(s)", len(results), len(errors))
        if errors:
            logger.warning("Pipeline errors: %s", errors)
        return results, errors

    async def _handle_callback(self, text, actor, reply_fn):
        """Process an incoming message through the pipeline and send replies."""
        logger.debug("Callback invoked: text='%s', actor='%s'", text, actor)

        loop = asyncio.get_running_loop()
        progress_queue: asyncio.Queue[str | None] = asyncio.Queue()

        def make_progress(plugin_name: str) -> QueueProgressReporter:
            return QueueProgressReporter(plugin_name, progress_queue, loop)

        async def drain_progress():
            while True:
                msg = await progress_queue.get()
                if msg is None:
                    break
                await reply_fn("progress", {"text": msg})

        drain_task = asyncio.create_task(drain_progress())
        try:
            results, errors = await self.handle_message(text, actor, progress_factory=make_progress)
        finally:
            await progress_queue.put(None)
            await drain_task

        for plugin_name, response in results:
            logger.debug("Dispatching reply for '%s' back to transport", plugin_name)
            await reply_fn(plugin_name, response)
        for plugin_name, error_msg in errors:
            logger.debug("Dispatching error reply for '%s': %s", plugin_name, error_msg)
            friendly = f"I am terribly sorry, {plugin_name} just does not want to behave!"
            await reply_fn("error", {"text": friendly})
        if not results and not errors:
            await reply_fn("sandy", {"text": "Sorry, I'm not sure how to do that."})

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
            task = asyncio.create_task(transport.listen(self._handle_callback))
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
