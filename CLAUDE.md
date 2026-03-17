# Sandy — Claude Code Configuration

## What Is Sandy

Sandy is a CLI tool that routes freeform text commands to plugins. Inspired by
[I Want Sandy](https://boingboing.net/2007/11/14/i-want-sandy-perfect.html). The goal
is to "bring delight" — surfacing things you care about with minimal friction.

Fan-out model: **all** matching plugins respond to a command, not just the first match.

## Key Docs

- **Project doc** (Obsidian): `/Users/tom/Documents/notes/tclancy/Dispatch/Projects/Sandy.md`
- **Design spec**: `docs/specs/2026-03-10-sandy-mvp-design.md`
- **Implementation plan**: `docs/plans/2026-03-10-sandy-mvp.md`

## Architecture

```
sandy "some text"
  → cli.py (argparse, --actor flag)
  → pipeline.py (run_pipeline: loader → matcher → handlers)
  → each matching plugin's handle(text, actor) → dict → stdout (formatted as plain text)

sandy serve
  → daemon.py (asyncio event loop, loads plugins once)
  → transport_loader.py (discovers transports from sandy/transports/)
  → each transport's listen() receives messages
  → pipeline.py routes to content plugins
  → transport's format_response() delivers back through channel
```

CLI mode is stateless. Daemon mode (`sandy serve`) is long-running and transport-driven.

## Plugin Contract

Each plugin is a `.py` file in `sandy/plugins/` that exposes:

- `name: str` — human-readable name (e.g. `"spotify"`)
- `commands: list[str]` — phrases to match (case-insensitive substring)
- `handle(text: str, actor: str) -> dict` — returns response dict with:
  - `text` (required): plain text response
  - `title` (optional): heading
  - `links` (optional): list of `{"label": str, "url": str}`
  - `image_url` (optional): image URL

Malformed plugins are skipped with a stderr warning, not a crash.
Partial plugin failure (some succeed, some raise) exits 0.
All matched plugins fail → exits non-zero.

## Transport Plugin Contract

Each transport is a `.py` file in `sandy/transports/` that exposes:

- `name: str` — transport identifier (e.g. `"slack"`)
- `async listen(callback)` — start listening, call `callback(text, actor, reply_fn)` for each message
- `format_response(plugin_name: str, response: dict) -> Any` — translate response dict to channel format

## Daemon Mode

`sandy serve` starts the daemon, which loads all plugins once and listens on configured transports.
Configure active transports in `sandy.toml`:

```toml
[daemon]
transports = ["slack"]
```

## Current Plugins

- **spotify** (`sandy/plugins/spotify.py`): new releases from followed artists
  - Commands: `"find me new music"`, `"new music"`
  - Requires `.env` with `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, `SPOTIPY_REDIRECT_URI`
  - Redirect URI must be `http://127.0.0.1:8888/callback` (not `localhost`) — Spotify dashboard must match
  - If `.cache` exists with a stale token, delete it and re-auth

- **cryptics** (`sandy/plugins/cryptics.py`): random puzzle from Hex or Mad Dog Cryptics, sent to printer
  - Commands: `"crossword"`
  - Requires `SANDY_PRINTER` in `.env` (default: `Brother_MFC_L2750DW_series`); find yours with `lpstat -p`
  - On print failure, returns the puzzle URL as fallback

- **slack** (`sandy/transports/slack.py`): Slack transport via Socket Mode
  - Requires `SLACK_APP_TOKEN` and `SLACK_BOT_TOKEN` in `.env` or `sandy.toml`
  - Socket Mode: no public URL needed, works behind NAT
  - Block Kit formatting for rich responses
  - Responds to DMs and @mentions

## Development

```bash
uv pip install -e .       # install in dev mode
uv run pytest -v          # run all tests
uv run sandy "find me new music"
```

Always use `uv`, never `pip`.

## Testing

- Back-end logic is unit-tested with pytest
- Spotify plugin tests mock the API (`unittest.mock`) — no real API calls in tests
- Test files live in `tests/`

## Conventions

- Do all work in a `claude/` branch
- Python 3.13+
- Prefer stateless solutions
- Plugin discovery is alphabetical by filename

## Known Issues / TODO

See `docs/SPOTIFY-AUTH-TODO.md` for Spotify OAuth troubleshooting.
