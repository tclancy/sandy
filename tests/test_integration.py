"""Integration tests: message flow through daemon + transport pipeline."""

import asyncio
import textwrap
from sandy.daemon import Daemon


def _make_dir(tmp_path, subdir, files):
    """Create a directory with Python files for tests."""
    d = tmp_path / subdir
    d.mkdir(exist_ok=True)
    (d / "__init__.py").write_text("")
    for filename, code in files.items():
        (d / filename).write_text(textwrap.dedent(code))
    return str(d)


def test_full_message_flow(tmp_path):
    """Message arrives via transport, routes through pipeline, gets formatted response."""
    plugin_dir = _make_dir(
        tmp_path,
        "plugins",
        {
            "greeter.py": """
            name = "greeter"
            commands = ["hello"]
            def handle(text, actor):
                return {"text": f"Hello, {actor}!", "title": "Greeting"}
        """
        },
    )
    transport_dir = _make_dir(tmp_path, "transports", {})

    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=transport_dir)

    async def run():
        results, errors = await daemon.handle_message("hello there", "michelle")
        assert len(results) == 1
        assert results[0][0] == "greeter"
        assert results[0][1]["text"] == "Hello, michelle!"
        assert results[0][1]["title"] == "Greeting"
        assert errors == []

    asyncio.run(run())


def test_full_flow_with_formatting(tmp_path):
    """Verify a transport's format_response works with real pipeline output."""
    plugin_dir = _make_dir(
        tmp_path,
        "plugins",
        {
            "greeter.py": """
            name = "greeter"
            commands = ["hello"]
            def handle(text, actor):
                return {
                    "text": f"Hello, {actor}!",
                    "title": "Greeting",
                    "links": [{"label": "More info", "url": "https://example.com"}],
                }
        """
        },
    )
    transport_dir = _make_dir(tmp_path, "transports", {})

    daemon = Daemon(plugin_dir=plugin_dir, transport_dir=transport_dir)

    from sandy.transports.slack import format_response

    async def run():
        results, errors = await daemon.handle_message("hello there", "tom")
        plugin_name, response = results[0]
        formatted = format_response(plugin_name, response)
        blocks = formatted["blocks"]
        block_types = [b["type"] for b in blocks]
        assert "header" in block_types
        assert "section" in block_types
        assert "context" in block_types

    asyncio.run(run())
