import asyncio
import textwrap
from sandy.daemon import Daemon


def _make_plugins(tmp_path, subdir, plugins):
    d = tmp_path / subdir
    d.mkdir(exist_ok=True)
    for filename, code in plugins.items():
        (d / filename).write_text(textwrap.dedent(code))
    return str(d)


def test_daemon_routes_message(tmp_path):
    """A message through the daemon reaches a content plugin and gets a response."""
    plugin_dir = _make_plugins(
        tmp_path,
        "plugins",
        {
            "echo.py": """
            name = "echo"
            commands = ["echo"]
            def handle(text, actor):
                return {"text": f"echo: {text}"}
        """
        },
    )

    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        results, errors = await daemon.handle_message("echo hello", "tom")
        assert len(results) == 1
        assert results[0][0] == "echo"
        assert results[0][1]["text"] == "echo: echo hello"

    asyncio.run(run())


def test_daemon_no_match(tmp_path):
    """A message with no matching plugin returns empty results."""
    plugin_dir = _make_plugins(
        tmp_path,
        "plugins",
        {
            "echo.py": """
            name = "echo"
            commands = ["echo"]
            def handle(text, actor):
                return {"text": "ok"}
        """
        },
    )

    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=str(tmp_path / "transports"))

    async def run():
        results, errors = await daemon.handle_message("unknown", "tom")
        assert results == []

    asyncio.run(run())
