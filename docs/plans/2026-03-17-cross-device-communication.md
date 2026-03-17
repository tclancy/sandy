# Cross-Device Communication Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Sandy reachable from any device via Slack, with a daemon that manages transport plugins alongside the existing content plugin pipeline.

**Architecture:** Sandy's core pipeline (loader, matcher, content plugins) becomes a library callable by both the CLI and a new daemon. The daemon hosts transport plugins (Slack first) that listen for messages and deliver formatted responses. Content plugins switch from returning strings to returning dicts with optional rich fields.

**Tech Stack:** Python 3.13+, slack-bolt (Socket Mode), asyncio, pytest

---

## File Structure

### New Files
- `sandy/transports/` — transport plugin directory
- `sandy/transports/__init__.py` — empty
- `sandy/transports/slack.py` — Slack transport plugin
- `sandy/daemon.py` — daemon entry point (`sandy serve`), event loop, transport orchestration
- `sandy/pipeline.py` — extracted core pipeline function (load plugins, match, handle, collect results)
- `sandy/transport_loader.py` — discovers and validates transport plugins from `sandy/transports/`
- `tests/test_pipeline.py` — tests for the extracted pipeline
- `tests/test_daemon.py` — tests for daemon startup/shutdown/message routing
- `tests/test_slack_transport.py` — tests for Slack transport formatting and message handling
- `tests/test_transport_loader.py` — tests for transport plugin discovery

### Modified Files
- `sandy/plugins/spotify.py` — `handle()` returns dict instead of str
- `sandy/plugins/cryptics.py` — `handle()` returns dict instead of str
- `sandy/plugins/hardcover.py` — `handle()` returns dict instead of str
- `sandy/plugins/real_men.py` — `handle()` returns dict instead of str
- `sandy/cli.py` — format dict responses as plain text, add `serve` subcommand
- `pyproject.toml` — add `slack-bolt` dependency
- `sandy.toml.example` — add `[daemon]` and `[slack]` sections
- `tests/test_cli.py` — mock plugins return dicts
- `tests/test_spotify.py` — expect dict responses
- `tests/test_cryptics.py` — expect dict responses
- `tests/test_hardcover.py` — expect dict responses
- `tests/test_real_men.py` — expect dict responses

---

## Task 1: Extract Core Pipeline

Pull the "load plugins, match, handle each, collect results" logic out of `cli.py` into a reusable function that both the CLI and daemon can call.

**Files:**
- Create: `sandy/pipeline.py`
- Create: `tests/test_pipeline.py`
- Modify: `sandy/cli.py`

- [ ] **Step 1: Write failing test for pipeline function**

```python
# tests/test_pipeline.py
import textwrap
from sandy.pipeline import run_pipeline


def _make_plugins(tmp_path, plugins):
    for filename, code in plugins.items():
        (tmp_path / filename).write_text(textwrap.dedent(code))
    return str(tmp_path)


def test_run_pipeline_returns_results(tmp_path):
    plugin_dir = _make_plugins(
        tmp_path,
        {
            "echo.py": """
            name = "echo"
            commands = ["echo"]
            def handle(text, actor):
                return {"text": f"echo: {text}"}
        """
        },
    )
    results, errors = run_pipeline("echo this", "tom", plugin_dir=plugin_dir)
    assert len(results) == 1
    assert results[0][0] == "echo"
    assert results[0][1]["text"] == "echo: echo this"
    assert errors == []


def test_run_pipeline_no_matches(tmp_path):
    plugin_dir = _make_plugins(
        tmp_path,
        {
            "echo.py": """
            name = "echo"
            commands = ["echo"]
            def handle(text, actor):
                return {"text": "ok"}
        """
        },
    )
    results, errors = run_pipeline("unknown", "tom", plugin_dir=plugin_dir)
    assert results == []
    assert errors == []


def test_run_pipeline_partial_failure(tmp_path):
    plugin_dir = _make_plugins(
        tmp_path,
        {
            "alpha.py": """
            name = "alpha"
            commands = ["test"]
            def handle(text, actor):
                raise RuntimeError("kaboom")
        """,
            "beta.py": """
            name = "beta"
            commands = ["test"]
            def handle(text, actor):
                return {"text": "beta worked"}
        """,
        },
    )
    results, errors = run_pipeline("test", "tom", plugin_dir=plugin_dir)
    assert len(results) == 1
    assert results[0][0] == "beta"
    assert len(errors) == 1
    assert "alpha" in errors[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_pipeline' from 'sandy.pipeline'`

- [ ] **Step 3: Implement pipeline.py**

```python
# sandy/pipeline.py
"""Core pipeline: match text against plugins, run handlers, collect results."""

import os

from sandy.config import apply_env, load_config
from sandy.loader import load_plugins
from sandy.matcher import find_matches


def _default_plugin_dir() -> str:
    return os.path.join(os.path.dirname(__file__), "plugins")


def run_pipeline(
    text: str,
    actor: str,
    plugin_dir: str | None = None,
    config: dict | None = None,
    plugins: list | None = None,
) -> tuple[list[tuple[str, dict]], list[str]]:
    """Run the Sandy pipeline: match text, call handlers, collect results.

    Args:
        text: The command text.
        actor: Who sent the command.
        plugin_dir: Directory to load plugins from. Ignored if plugins provided.
        config: Config dict. Loaded from default locations if None.
        plugins: Pre-loaded plugin list. If provided, skips loading.

    Returns:
        (results, errors) where results is a list of (plugin_name, response_dict)
        and errors is a list of error message strings.
    """
    if config is None:
        config = load_config()
        apply_env(config)

    if plugins is None:
        if plugin_dir is None:
            plugin_dir = _default_plugin_dir()
        plugins = load_plugins(plugin_dir, config)

    matches = find_matches(text, plugins)

    results = []
    errors = []
    for match in matches:
        try:
            response = match.handle(text, actor)
            results.append((match.name, response))
        except Exception as e:
            errors.append(f"{match.name} plugin failed: {e}")

    return results, errors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Refactor cli.py to use pipeline**

Update `sandy/cli.py` to call `run_pipeline()` instead of duplicating the logic. The CLI still formats output as plain text strings, but delegates the actual work to the pipeline.

```python
# sandy/cli.py
import argparse
import sys

from sandy.pipeline import run_pipeline


def _format_text(plugin_name: str, response: dict) -> str:
    """Format a plugin response dict as plain text for the CLI."""
    lines = [f"[{plugin_name}]"]
    if "title" in response:
        lines.append(response["title"])
    lines.append(response.get("text", ""))
    if "links" in response:
        for link in response["links"]:
            lines.append(f"  {link['label']}: {link['url']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Route text commands to plugins.")
    parser.add_argument("text", nargs="?", help="The command text to process")
    parser.add_argument("--actor", default="tom", help="Who is sending the command (default: tom)")
    args = parser.parse_args(argv)

    if not args.text:
        parser.print_usage(file=sys.stderr)
        return 1

    results, errors = run_pipeline(args.text, args.actor)

    for error in errors:
        print(error, file=sys.stderr)

    if not results and not errors:
        print("I don't know how to do that yet.")
        return 1

    for i, (plugin_name, response) in enumerate(results):
        if i > 0:
            print()
        print(_format_text(plugin_name, response))

    return 0 if results else 1


def cli():
    """Entry point for the `sandy` console script."""
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nWrapping up early today!")
        sys.exit(0)
```

- [ ] **Step 6: Run all tests to verify nothing broke**

Run: `uv run pytest -v`
Expected: Existing CLI tests will FAIL because mock plugins still return strings — the CLI now expects dicts. This is an intermediate state on the feature branch. The new pipeline tests should all pass. Existing CLI tests are fixed in Task 2 (the next task). Do NOT commit until Task 2 is also complete.

**Important:** Tasks 1 and 2 are logically atomic. Proceed directly to Task 2 before committing. The commit at the end of Task 2 covers both tasks.

- [ ] **Step 7: Commit (deferred to Task 2, Step 11)**

Do not commit yet — wait until Task 2 completes so the test suite is green.

---

## Task 2: Switch Content Plugins to Dict Responses (Atomic)

Update all 4 content plugins to return dicts, and update all tests to match. This is a single atomic change — everything switches at once.

**Files:**
- Modify: `sandy/plugins/spotify.py`
- Modify: `sandy/plugins/cryptics.py`
- Modify: `sandy/plugins/hardcover.py`
- Modify: `sandy/plugins/real_men.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_spotify.py`
- Modify: `tests/test_cryptics.py`
- Modify: `tests/test_hardcover.py`
- Modify: `tests/test_real_men.py`

- [ ] **Step 1: Update spotify.py handle() to return dict**

The spotify plugin currently builds a multi-line string with release info. Convert to dict with `text`, `title`, and `links` fields.

```python
# sandy/plugins/spotify.py — handle() change
def handle(text: str, actor: str) -> dict:
    try:
        sp = _get_spotify_client()
    except Exception as e:
        return {"text": f"Spotify auth failed: {e}"}

    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    artists = _get_followed_artists(sp)

    if not artists:
        return {"text": "You don't follow any artists on Spotify."}

    lines = []
    links = []
    found = 0

    for artist in artists:
        for album in _get_recent_releases(sp, artist["id"], since):
            album_type = album["album_type"].capitalize()
            url = album["external_urls"].get("spotify", "")
            label = f"{artist['name']} — {album['name']} ({album_type}, {album['release_date']})"
            lines.append(f"- {label} {url}")
            if url:
                links.append({"label": label, "url": url})
            found += 1

    if found == 0:
        return {"text": f"No new releases from artists you follow in the last {LOOKBACK_DAYS} days."}

    return {
        "title": f"New releases from artists you follow (last {LOOKBACK_DAYS} days):",
        "text": "\n".join(lines),
        "links": links,
    }
```

- [ ] **Step 2: Update cryptics.py handle() to return dict**

```python
# sandy/plugins/cryptics.py — handle() change
def handle(text: str, actor: str) -> dict:
    source_name, fetcher = random.choice(SOURCES)
    try:
        puzzle_page, pdf_url = fetcher()
    except Exception as e:
        return {"text": f"Couldn't fetch a crossword from {source_name}: {e}"}

    try:
        _print_pdf(pdf_url)
    except Exception as e:
        return {
            "text": f"Got a puzzle from {source_name} but printing failed: {e}",
            "links": [{"label": f"{source_name} puzzle", "url": puzzle_page}],
        }

    return {"text": f"Printing your crossword from {source_name}. Enjoy!"}
```

- [ ] **Step 3: Update hardcover.py handle() to return dict**

```python
# sandy/plugins/hardcover.py — handle() change
def handle(text: str, actor: str) -> dict:
    token = _get_token()
    want_to_read = _fetch_want_to_read(token)
    in_dover = _fetch_in_dover(token)

    want_ids = {b["id"] for b in want_to_read}
    candidates = [b for b in in_dover if b["id"] in want_ids]

    if not candidates:
        return {"text": "No books found that are both in your Dover list and on your Want to Read shelf."}

    book = random.choice(candidates)
    url = _build_search_url(book["title"])
    return {
        "text": f"{book['title']} by {book['author']}",
        "links": [{"label": "Reserve at Dover Library", "url": url}],
    }
```

- [ ] **Step 4: Update real_men.py handle() to return dict**

```python
# sandy/plugins/real_men.py — handle() change
def handle(text: str, actor: str) -> dict:
    urls = _get_mp3_urls()
    if not urls:
        raise ValueError("No Real Men of Genius tracks found.")
    url = random.choice(urls)
    filename = url.split("/")[-1]
    title = requests.utils.unquote(filename).removesuffix(".mp3")
    _play_mp3(url)
    return {"text": f"Real Men of Genius presents: {title}"}
```

- [ ] **Step 5: Update test_cli.py mock plugins to return dicts**

Every mock plugin's `handle()` function must return a dict instead of a string. Update the assertions to check for the dict's `text` field in the formatted output.

Key changes for each test:
- `return f"echo: {text} (from {actor})"` → `return {"text": f"echo: {text} (from {actor})"}`
- `return "alpha summary"` → `return {"text": "alpha summary"}`
- `return "beta summary"` → `return {"text": "beta summary"}`
- `return "ok"` → `return {"text": "ok"}`
- `return "beta worked"` → `return {"text": "beta worked"}`

Assertion changes: the output format from `_format_text()` now includes the `[plugin_name]` header followed by the text on the next line. Verify assertions still match this format.

- [ ] **Step 6: Update test_spotify.py to expect dicts**

All assertions that check `handle()` return values need to expect dicts. For example:
- `assert "New releases" in result` → `assert "New releases" in result["title"]`
- `assert "No new releases" in result` → `assert "No new releases" in result["text"]`

Read the full test file and update each assertion accordingly.

- [ ] **Step 7: Update test_cryptics.py to expect dicts**

Same pattern: assertions check `result["text"]` or `result.get("links")` instead of the raw string.

- [ ] **Step 8: Update test_hardcover.py to expect dicts**

Same pattern. The hardcover plugin now returns `links` for the library URL, so assertions should check both `result["text"]` and `result["links"]`.

- [ ] **Step 9: Update test_real_men.py to expect dicts**

Same pattern: `assert "Real Men of Genius presents" in result["text"]`.

- [ ] **Step 10: Run all tests**

Run: `uv run pytest -v`
Expected: All tests PASS (99 existing + 3 new pipeline tests)

- [ ] **Step 11: Commit**

```bash
git add sandy/pipeline.py sandy/cli.py sandy/plugins/ tests/
git commit -m "feat: extract pipeline and switch plugins to dict responses

Extracts core pipeline from CLI for reuse by daemon. All content plugins
now return dicts with 'text' (required) and optional 'title', 'links',
'image_url' fields. CLI formats dicts as plain text.
This enables transport plugins to render rich output (Block Kit, etc.)."
```

---

## Task 3: Transport Loader

Build the loader that discovers transport plugins from `sandy/transports/`, analogous to the existing content plugin loader.

**Files:**
- Create: `sandy/transports/__init__.py`
- Create: `sandy/transport_loader.py`
- Create: `tests/test_transport_loader.py`

- [ ] **Step 1: Create transports directory**

```bash
mkdir -p sandy/transports
touch sandy/transports/__init__.py
```

- [ ] **Step 2: Write failing tests for transport loader**

```python
# tests/test_transport_loader.py
import textwrap
from sandy.transport_loader import load_transports


def _make_transport(tmp_path, filename, code):
    (tmp_path / filename).write_text(textwrap.dedent(code))
    return str(tmp_path)


def test_load_valid_transport(tmp_path):
    _make_transport(
        tmp_path,
        "test_channel.py",
        """
        name = "test_channel"
        async def listen(callback):
            pass
        def format_response(plugin_name, response):
            return response["text"]
    """,
    )
    transports = load_transports(str(tmp_path))
    assert len(transports) == 1
    assert transports[0].name == "test_channel"


def test_skip_malformed_transport(tmp_path, capsys):
    _make_transport(
        tmp_path,
        "bad.py",
        """
        name = "bad"
        # missing listen and format_response
    """,
    )
    transports = load_transports(str(tmp_path))
    assert transports == []
    assert "missing" in capsys.readouterr().err.lower()


def test_skip_inactive_transport(tmp_path):
    _make_transport(
        tmp_path,
        "disabled.py",
        """
        name = "disabled"
        async def listen(callback):
            pass
        def format_response(plugin_name, response):
            return ""
    """,
    )
    config = {"daemon": {"transports": ["other"]}}
    transports = load_transports(str(tmp_path), config=config)
    assert transports == []


def test_load_only_active_transports(tmp_path):
    _make_transport(
        tmp_path,
        "alpha.py",
        """
        name = "alpha"
        async def listen(callback):
            pass
        def format_response(plugin_name, response):
            return ""
    """,
    )
    _make_transport(
        tmp_path,
        "beta.py",
        """
        name = "beta"
        async def listen(callback):
            pass
        def format_response(plugin_name, response):
            return ""
    """,
    )
    config = {"daemon": {"transports": ["alpha"]}}
    transports = load_transports(str(tmp_path), config=config)
    assert len(transports) == 1
    assert transports[0].name == "alpha"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_transport_loader.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 4: Implement transport_loader.py**

```python
# sandy/transport_loader.py
"""Discover and validate transport plugins from sandy/transports/."""

import importlib.util
import os
import sys

REQUIRED_ATTRS = ("name", "listen", "format_response")


def load_transports(
    transport_dir: str, config: dict | None = None
) -> list:
    """Discover and load valid transport plugins from a directory.

    If config has a [daemon] section with a transports list,
    only transports whose name appears in that list are returned.
    """
    if config is None:
        config = {}
    active_list = config.get("daemon", {}).get("transports")

    transports = []
    if not os.path.isdir(transport_dir):
        return transports

    filenames = sorted(
        f for f in os.listdir(transport_dir) if f.endswith(".py") and f != "__init__.py"
    )

    for filename in filenames:
        filepath = os.path.join(transport_dir, filename)
        module_name = f"sandy_transport_{os.path.abspath(filepath).replace('/', '_')}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                print(f"Warning: could not create loader for {filename}", file=sys.stderr)
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"Warning: failed to load transport {filename}: {e}", file=sys.stderr)
            continue

        missing = [attr for attr in REQUIRED_ATTRS if not hasattr(module, attr)]
        if missing:
            print(
                f"Warning: skipping transport {filename}: missing {', '.join(missing)}",
                file=sys.stderr,
            )
            continue

        if not callable(getattr(module, "listen")):
            print(f"Warning: skipping transport {filename}: listen is not callable", file=sys.stderr)
            continue

        if active_list is not None and module.name not in active_list:
            continue

        transports.append(module)

    return transports
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_transport_loader.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add sandy/transports/__init__.py sandy/transport_loader.py tests/test_transport_loader.py
git commit -m "feat: add transport plugin loader

Discovers transport plugins from sandy/transports/, validates they have
name/listen/format_response, filters by [daemon].transports config list."
```

---

## Task 4: Daemon

Build the daemon process that starts transport plugins and routes messages through the core pipeline.

**Files:**
- Create: `sandy/daemon.py`
- Create: `tests/test_daemon.py`
- Modify: `sandy/cli.py` (add `serve` subcommand)

- [ ] **Step 1: Write failing tests for daemon**

```python
# tests/test_daemon.py
import asyncio
import textwrap
from unittest.mock import AsyncMock, patch
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_daemon.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement daemon.py**

```python
# sandy/daemon.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_daemon.py -v`
Expected: Both tests PASS

- [ ] **Step 5: Add `serve` subcommand to CLI**

Update `sandy/cli.py` to use subcommands. `sandy "text"` still works as before (default behavior). `sandy serve` starts the daemon.

Modify the argument parser to support both modes:
- `sandy "find me new music"` — runs the one-shot CLI pipeline (positional text arg)
- `sandy serve` — starts the daemon

**Note:** argparse subparsers and positional args on the root parser conflict — `sandy serve` would be consumed by the `text` positional. Instead, detect `serve` before argparse runs:

```python
# In sandy/cli.py, update main():
def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # Handle `sandy serve` before argparse (avoids subparser/positional conflict)
    if argv and argv[0] == "serve":
        from sandy.daemon import serve
        serve()
        return 0

    parser = argparse.ArgumentParser(description="Route text commands to plugins.")
    parser.add_argument("text", nargs="?", help="The command text to process")
    parser.add_argument("--actor", default="tom", help="Who is sending the command (default: tom)")
    args = parser.parse_args(argv)

    if not args.text:
        parser.print_usage(file=sys.stderr)
        return 1

    # ... rest of existing CLI logic (run_pipeline, format, print)
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add sandy/daemon.py tests/test_daemon.py sandy/cli.py
git commit -m "feat: add Sandy daemon with serve subcommand

Daemon loads plugins once at startup, routes messages through the core
pipeline using asyncio.to_thread, manages transport lifecycles, and
handles SIGTERM/SIGINT for clean shutdown."
```

---

## Task 5: Slack Transport Plugin

Build the Slack transport using slack-bolt Socket Mode.

**Files:**
- Modify: `pyproject.toml` (add slack-bolt dependency)
- Create: `sandy/transports/slack.py`
- Create: `tests/test_slack_transport.py`
- Modify: `sandy.toml.example`

- [ ] **Step 1: Add slack-bolt dependency**

```bash
uv add slack-bolt
```

- [ ] **Step 2: Write failing tests for Slack transport**

```python
# tests/test_slack_transport.py
from sandy.transports.slack import format_response


def test_format_response_text_only():
    """Plain text response produces a section block."""
    result = format_response("echo", {"text": "hello world"})
    blocks = result["blocks"]
    # Context block with plugin name
    assert any(
        b["type"] == "context" for b in blocks
    )
    # Section block with text
    section = next(b for b in blocks if b["type"] == "section")
    assert "hello world" in section["text"]["text"]


def test_format_response_with_title():
    """Response with title produces a header block."""
    result = format_response("spotify", {
        "title": "New releases",
        "text": "Artist — Album",
    })
    blocks = result["blocks"]
    header = next(b for b in blocks if b["type"] == "header")
    assert "New releases" in header["text"]["text"]


def test_format_response_with_links():
    """Response with links includes them in a section."""
    result = format_response("hardcover", {
        "text": "Book Title by Author",
        "links": [{"label": "Reserve", "url": "https://example.com"}],
    })
    blocks = result["blocks"]
    # Find section with link
    link_sections = [
        b for b in blocks
        if b["type"] == "section" and "Reserve" in b["text"]["text"]
    ]
    assert len(link_sections) == 1
    assert "https://example.com" in link_sections[0]["text"]["text"]


def test_format_response_with_image():
    """Response with image_url includes an image block."""
    result = format_response("test", {
        "text": "Check this out",
        "image_url": "https://example.com/image.png",
    })
    blocks = result["blocks"]
    image = next(b for b in blocks if b["type"] == "image")
    assert image["image_url"] == "https://example.com/image.png"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_slack_transport.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 4: Implement slack transport**

```python
# sandy/transports/slack.py
"""Slack transport plugin for Sandy.

Uses Socket Mode (no public URL needed). Listens for DMs and @mentions,
routes text through Sandy's pipeline, replies with Block Kit formatted messages.
"""

import os

name = "slack"


def _get_tokens() -> tuple[str, str]:
    app_token = os.environ.get("SLACK_APP_TOKEN", "")
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not app_token or not bot_token:
        raise RuntimeError(
            "SLACK_APP_TOKEN and SLACK_BOT_TOKEN must be set. "
            "Add them to sandy.toml under [slack]."
        )
    return app_token, bot_token


def format_response(plugin_name: str, response: dict) -> dict:
    """Translate a content plugin response dict into Slack Block Kit blocks."""
    blocks = []

    if "title" in response:
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": response["title"][:150]},
        })

    if "text" in response:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": response["text"][:3000]},
        })

    if "links" in response:
        link_lines = [f"<{link['url']}|{link['label']}>" for link in response["links"]]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(link_lines)},
        })

    if "image_url" in response:
        blocks.append({
            "type": "image",
            "image_url": response["image_url"],
            "alt_text": response.get("title", plugin_name),
        })

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"via *{plugin_name}*"}],
    })

    return {"blocks": blocks}


async def listen(callback):
    """Start the Slack Socket Mode listener.

    callback signature: async callback(text, actor, reply_fn)
    """
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

    app_token, bot_token = _get_tokens()
    app = AsyncApp(token=bot_token)

    @app.event("message")
    async def handle_message(event, say):
        text = event.get("text", "").strip()
        if not text:
            return

        # Strip bot mention if present (e.g., "<@U12345> find me new music")
        if text.startswith("<@"):
            text = text.split(">", 1)[-1].strip()

        actor = event.get("user", "unknown")

        # Try to get display name for actor
        try:
            user_info = await app.client.users_info(user=actor)
            actor = user_info["user"]["profile"].get("display_name") or user_info["user"]["name"]
            actor = actor.lower()
        except Exception:
            pass

        async def reply_fn(plugin_name, response):
            formatted = format_response(plugin_name, response)
            await say(blocks=formatted["blocks"])

        await callback(text, actor, reply_fn)

    handler = AsyncSocketModeHandler(app, app_token)
    await handler.start_async()
```

- [ ] **Step 5: Run Slack transport tests**

Run: `uv run pytest tests/test_slack_transport.py -v`
Expected: All 4 tests PASS (these only test `format_response`, no Slack API calls)

- [ ] **Step 6: Update sandy.toml.example**

Add `[daemon]` and `[slack]` sections to `sandy.toml.example`:

```toml
# ---- Daemon Configuration ----
# Controls which transports are active when running `sandy serve`
[daemon]
transports = ["slack"]

# ---- Slack Transport ----
[slack]
# Get these from https://api.slack.com/apps — Socket Mode must be enabled
SLACK_APP_TOKEN = "xapp-..."
SLACK_BOT_TOKEN = "xoxb-..."
```

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock sandy/transports/slack.py tests/test_slack_transport.py sandy.toml.example
git commit -m "feat: add Slack transport plugin

Socket Mode via slack-bolt, Block Kit formatting for rich responses,
DM and @mention support, actor derived from Slack display name."
```

---

## Task 6: Integration Test & Final Wiring

End-to-end test: mock transport → daemon → mock content plugin → formatted response.

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration.py
import asyncio
import textwrap
from sandy.daemon import Daemon


def _make_dir(tmp_path, subdir, files):
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

    # Import Slack formatter and verify it can format the response
    from sandy.transports.slack import format_response

    async def run():
        results, errors = await daemon.handle_message("hello there", "tom")
        plugin_name, response = results[0]
        formatted = format_response(plugin_name, response)
        blocks = formatted["blocks"]
        # Should have: header, text section, links section, context
        block_types = [b["type"] for b in blocks]
        assert "header" in block_types
        assert "section" in block_types
        assert "context" in block_types

    asyncio.run(run())
```

- [ ] **Step 2: Run integration tests**

Run: `uv run pytest tests/test_integration.py -v`
Expected: All tests PASS

- [ ] **Step 3: Run full test suite with coverage**

Run: `uv run pytest -v`
Expected: All tests PASS, coverage >= 80%

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration tests for daemon + transport pipeline"
```

---

## Task 7: Documentation & Cleanup

Update CLAUDE.md and config example, final review.

**Files:**
- Modify: `CLAUDE.md`
- Modify: `sandy.toml.example`

- [ ] **Step 1: Update CLAUDE.md**

Add documentation for:
- The `sandy serve` command
- Transport plugin contract
- Slack transport setup instructions (Slack app creation, Socket Mode, tokens)
- Updated plugin contract (dict return type)

- [ ] **Step 2: Run full test suite one final time**

Run: `uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md sandy.toml.example
git commit -m "docs: update CLAUDE.md for daemon and Slack transport"
```

- [ ] **Step 4: Push branch and create PR**

```bash
git push -u origin claude/cross-device-comms-issue-12
gh pr create --title "Add daemon mode with Slack transport" --body "..."
```
