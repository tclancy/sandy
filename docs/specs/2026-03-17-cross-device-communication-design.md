# Cross-Device Communication Design

**Date:** 2026-03-17
**Status:** Approved
**GitHub Issue:** #12

## Overview

Sandy becomes a daemon that listens for incoming messages on multiple channels and returns responses through those same channels. The core pipeline (loader, matcher, content plugins) remains unchanged, but gets wrapped in a long-running process that manages transport plugins — a new category of plugin responsible for receiving input and delivering formatted output.

The CLI remains a standalone one-shot entry point that calls the core pipeline directly, primarily for development and debugging.

## Plugin Taxonomy

Sandy now has two kinds of plugins:

### Content Plugins (existing)

Process commands and return structured responses. Live in `sandy/plugins/`.

```python
name: str                    # "spotify"
commands: list[str]          # ["find me new music", "new music"]

def handle(text: str, actor: str) -> dict:
    return {
        "text": "Plain text response",            # required
        "title": "Optional heading",              # optional
        "links": [{"label": "...", "url": "..."}], # optional
        "image_url": "https://...",               # optional
        # future fields as needed
    }
```

The dict is a loose contract — plugins include whatever fields make sense. Only `text` is required. Transport plugins use what they understand and ignore the rest.

**Breaking change:** `handle()` returns a `dict` instead of a `str`. All existing plugins (spotify, cryptics, hardcover, real_men) must be updated. This is an atomic change — all content plugins, the CLI output formatting, and all tests are updated in a single step. There is no compatibility shim; the old string return format is simply replaced.

### Transport Plugins (new)

Receive messages from a channel and deliver responses back. Live in `sandy/transports/`.

```python
name: str                    # "slack"

async def listen(callback):
    """Receive messages, call callback(text, actor, reply_fn) for each."""
    ...

def format_response(plugin_name: str, response: dict) -> Any:
    """Translate a content plugin's response dict into channel-native format."""
    ...
```

Transport plugins are distinguished from content plugins by directory (`sandy/transports/` vs `sandy/plugins/`), not by a flag.

The CLI is a special case — it doesn't `listen()`, it calls the pipeline directly and formats response dicts as plain text to stdout.

## Architecture & Message Flow

```
                    +---------------------------+
                    |       Sandy Daemon        |
                    |                           |
  Slack --listen()--+   +--------------------+  |
                    |   |   Core Pipeline    |  |
  (future)---------+   |                    |  |
                    |   |  loader -> matcher |  |
                    |   |  -> handle() each  |  |
                    |   +--------------------+  |
                    +---------------------------+
                              |
  CLI -----calls directly-----+  (no daemon needed)
```

### Daemon

Started via `sandy serve` — a new subcommand. Runs on the target machine (e.g., homelab). On startup: loads all plugins (content + transport) once and caches them, then calls `listen()` on each active transport plugin. The daemon owns the event loop. Handles SIGTERM/SIGINT gracefully (clean shutdown, close transport connections).

### Message Flow

1. Transport receives input (e.g., Slack message in a DM or channel)
2. Transport calls `callback(text, actor, reply_fn)` — actor derived from the channel (e.g., Slack username)
3. Callback runs the core pipeline: match against cached content plugins, call `handle()` on each match, collect response dicts
4. Callback passes each `(plugin_name, response_dict)` pair back to `reply_fn`
5. `reply_fn` is owned by the transport — it calls its own `format_response()` internally and delivers the result through the channel

The transport owns the full output path: it provides `reply_fn`, which knows how to format and deliver. The daemon's callback is only responsible for running the core pipeline and calling `reply_fn` with the raw results.

### Async Model

The daemon uses `asyncio` since Slack's Socket Mode (via `slack-bolt`) is async-native. Content plugins remain synchronous — the daemon wraps them in `asyncio.to_thread()` so they don't block the event loop.

### CLI

`sandy "crossword"` imports the core pipeline directly, runs it, formats response dicts as plain text, exits. No daemon involved.

## Slack Transport

### Connection

Slack Socket Mode via `slack-bolt`. Makes an outbound WebSocket connection to Slack — no public URL needed. Works behind NAT on homelab.

### Identity

- Registered as a Slack app with a bot user ("Sandy")
- Custom icon (from `assets/`)
- Responds in the same channel/DM where the message was received

### Triggering

- **DMs to Sandy:** Every message is treated as a command
- **In channels:** Sandy responds when @mentioned (e.g., `@Sandy find me new music`)

### Response Formatting

The Slack transport's `format_response()` translates response dicts into Block Kit:

- `title` → Header block
- `text` → Section block (with mrkdwn)
- `links` → Section with link-formatted text
- `image_url` → Image block
- Plugin name shown as context block at the bottom (like the `[spotify]` header in CLI today)
- Falls back to plain `text` in a section block if no rich fields are present

### Actor Mapping

Slack display name → `actor` parameter. If Michelle messages Sandy in Slack, plugins receive `actor="michelle"`.

## Configuration

### `sandy.toml` Additions

```toml
[daemon]
transports = ["slack"]

[slack]
SLACK_APP_TOKEN = "${SLACK_APP_TOKEN}"
SLACK_BOT_TOKEN = "${SLACK_BOT_TOKEN}"
```

### Plugin Discovery

- `sandy/plugins/*.py` → content plugins (existing)
- `sandy/transports/*.py` → transport plugins (new)
- Both validated at load time; malformed ones skipped with stderr warning (same as today)
- The `[daemon]` section's `transports` list controls which transport plugins are activated

## Error Handling

Same philosophy as today — partial failure is OK.

- **Transport fails to connect** (e.g., bad Slack token): log error, continue running other transports. If all transports fail, daemon exits non-zero.
- **Content plugin raises during `handle()`:** Same as today — report to logs, return error to the user through the transport ("spotify plugin failed"), continue with other matches.
- **Transport loses connection** (Slack WebSocket drops): reconnect automatically. `slack-bolt` handles this natively with Socket Mode.
- **Malformed transport plugin:** Skip with warning, same as content plugins.

## Testing

- **Core pipeline:** Already tested. Response dict contract change means updating existing tests to expect dicts instead of strings.
- **Transport plugins:** Each transport gets its own test file. Mock the external service (Slack API), verify that `format_response()` produces correct Block Kit, verify `listen()` calls the callback correctly.
- **Integration:** A test that wires a mock transport to the real pipeline with a mock content plugin, verifying the full message flow end-to-end.
- **No real Slack calls in tests** — same mock philosophy as the Spotify plugin.

## Out of Scope

- Scheduled/proactive messages (cron-style)
- Deployment specifics (systemd, Docker, etc.) — decided later
- AI/LLM processing of messages
- Multi-workspace Slack support
- Any transport other than Slack and CLI
