"""Sandy daemon: hosts transport plugins, routes messages through the core pipeline."""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from sandy.config import apply_env, load_config
from sandy.loader import load_plugins
from sandy.pipeline import run_pipeline
from sandy.printer import print_pdf
from sandy.progress import QueueProgressReporter
from sandy.transport_loader import load_transports

logger = logging.getLogger(__name__)

_RELOAD_INTERVAL = 2.0  # seconds between plugin directory polls


def _plugin_snapshot(plugin_dir: str) -> dict[str, float]:
    """Return {filepath: mtime} for all .py plugin files (follows symlinks)."""
    return {
        str(p): p.stat().st_mtime for p in Path(plugin_dir).glob("*.py") if p.name != "__init__.py"
    }


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

        self.plugin_dir = plugin_dir
        self.plugins = load_plugins(plugin_dir, config)
        self._plugin_mtimes = _plugin_snapshot(plugin_dir)
        logger.info(
            "Loaded %d content plugin(s): %s", len(self.plugins), [p.name for p in self.plugins]
        )
        self.transports = load_transports(transport_dir, config)
        logger.info(
            "Loaded %d transport(s): %s", len(self.transports), [t.name for t in self.transports]
        )

    async def handle_message(
        self, text: str, actor: str, progress_factory=None, tz: str | None = None
    ) -> tuple[list[tuple[str, dict]], list[tuple[str, str]]]:
        """Run the pipeline in a thread so sync plugins don't block the event loop."""
        logger.debug("Routing message to pipeline: text='%s', actor='%s', tz='%s'", text, actor, tz)
        results, errors = await asyncio.to_thread(
            run_pipeline,
            text,
            actor,
            plugins=self.plugins,
            config=self.config,
            progress_factory=progress_factory,
            tz=tz,
        )
        logger.info("Pipeline returned %d result(s), %d error(s)", len(results), len(errors))
        if errors:
            logger.warning("Pipeline errors: %s", errors)
        return results, errors

    async def _handle_callback(self, text, actor, reply_fn, tz: str | None = None):
        """Process an incoming message through the pipeline and send replies."""
        logger.debug("Callback invoked: text='%s', actor='%s', tz='%s'", text, actor, tz)

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
            results, errors = await self.handle_message(
                text, actor, progress_factory=make_progress, tz=tz
            )
        finally:
            await progress_queue.put(None)
            await drain_task

        for plugin_name, response in results:
            logger.debug("Dispatching reply for '%s' back to transport", plugin_name)
            if "pdf_url" in response:
                response = await self._handle_pdf_response(response)
            await reply_fn(plugin_name, response)
        for plugin_name, error_msg in errors:
            logger.debug("Dispatching error reply for '%s': %s", plugin_name, error_msg)
            friendly = f"I am terribly sorry, {plugin_name} just does not want to behave!"
            await reply_fn("error", {"text": friendly})
        if not results and not errors:
            await reply_fn("sandy", {"text": "Sorry, I'm not sure how to do that."})

    async def _handle_pdf_response(self, response: dict) -> dict:
        """Attempt to print a PDF and update the response text to reflect the outcome.

        The pdf_url field is consumed here (server-side print) and is not
        forwarded to the transport — transports don't know about printers.
        """
        pdf_url = response["pdf_url"]
        success, detail = await asyncio.to_thread(print_pdf, pdf_url)
        response = {k: v for k, v in response.items() if k != "pdf_url"}
        if not success:
            original_text = response.get("text", "")
            suffix = (
                f" — but printing failed: {detail}"
                if detail
                else " — but the printer did not respond. Is it on?"
            )
            response["text"] = original_text.rstrip(".") + suffix
        return response

    async def _watch_plugins(self) -> None:
        """Poll plugin directory every _RELOAD_INTERVAL seconds and reload on change.

        Uses Path.stat().st_mtime (follows symlinks) so changes to symlinked plugin
        files are detected correctly — the mtime of the symlink target is compared.
        New files and deleted files both trigger a reload.

        If load_plugins raises (e.g. a plugin file has a syntax error), the previous
        plugin set is kept active and the watcher continues polling.
        """
        while True:
            await asyncio.sleep(_RELOAD_INTERVAL)
            try:
                current = _plugin_snapshot(self.plugin_dir)
            except OSError:
                continue
            if current != self._plugin_mtimes:
                logger.info("Plugin directory changed — reloading plugins")
                try:
                    new_plugins = load_plugins(self.plugin_dir, self.config)
                except Exception:
                    logger.exception("Failed to reload plugins — keeping previous plugin set")
                    continue
                self.plugins = new_plugins
                self._plugin_mtimes = current
                logger.info(
                    "Reloaded %d plugin(s): %s",
                    len(self.plugins),
                    [p.name for p in self.plugins],
                )

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
        tasks.append(asyncio.create_task(self._watch_plugins()))
        logger.info("Plugin watcher started (polling every %.1fs)", _RELOAD_INTERVAL)

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
