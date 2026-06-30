# Sandy — Claude Code Configuration

## What Is Sandy

Sandy is a CLI tool and Slack bot that routes freeform text commands to plugins.
Inspired by [I Want Sandy](https://boingboing.net/2007/11/14/i-want-sandy-perfect.html).
The goal is to "bring delight" — surfacing things you care about with minimal friction.

Fan-out model: **all** matching plugins respond to a command, not just the first match.

### Orchestration Role

Sandy is the **unified control plane** for Tom's homelab automation. All specialist
tools (itguy for deploys, estimatedtaxes for tax tracking) live as sibling repos on
`homelab.local` and are exposed through Sandy plugins via subprocess calls.

```
homelab.local (/home/tom/sources/)
├── homelab/         Ansible playbooks (connection: local)
├── sandy/       Orchestrator — systemd service, plugins, Slack transport
├── itguy/       Deploy engine — Ansible + git-pull strategies
└── irs/         1099 tax tracking CLI (estimatedtaxes)
```

Everything runs co-located. No SSH hops, no Docker for Sandy itself.
See the Orchestration project doc in Obsidian for full context:
`/Users/tom/Documents/notes/tclancy/Dispatch/Projects/Orchestration.md`

## Key Docs

- **Project doc** (Obsidian): `/Users/tom/Documents/notes/tclancy/Dispatch/Projects/Sandy.md`
- **Orchestration doc** (Obsidian): `/Users/tom/Documents/notes/tclancy/Dispatch/Projects/Orchestration.md`
- **Design spec**: `docs/specs/2026-03-10-sandy-mvp-design.md`
- **Cross-device spec**: `docs/specs/2026-03-17-cross-device-communication-design.md`
- **Implementation plan**: `docs/plans/2026-03-10-sandy-mvp.md`

## Architecture

```
sandy "some text"
  → cli.py (argparse, --actor flag, --timezone flag)
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

### Core Modules

- **cli.py** — entry point, output formatting (field formatters for text/links/audio/pdf)
- **pipeline.py** — `run_pipeline()` orchestration, plugin introspection for optional params
- **loader.py** — dynamic plugin discovery from `sandy/plugins/`, validation, activation
- **matcher.py** — text normalization (strips punctuation, polite words), substring matching
- **config.py** — TOML config loading, env var injection, plugin activation
- **daemon.py** — asyncio event loop, message routing, progress queue draining
- **transport_loader.py** — transport discovery from `sandy/transports/`
- **printer.py** — PDF download + printing (CUPS and IPP URI support)
- **progress.py** — real-time status reporting (CLI stderr / daemon async queue)

## Plugin Contract

Each plugin is a `.py` file in `sandy/plugins/` that exposes:

- `name: str` — human-readable name (e.g. `"spotify"`)
- `commands: list[str]` — phrases to match (case-insensitive substring)
- `handle(text: str, actor: str) -> dict` — returns response dict with:
  - `text` (required): plain text response
  - `title` (optional): heading
  - `links` (optional): list of `{"label": str, "url": str}`
  - `image_url` (optional): image URL
  - `audio_url` (optional): audio URL (CLI downloads + plays via `afplay`)
  - `pdf_url` (optional): PDF URL (CLI downloads + prints; daemon prints on server)

`handle()` may also accept optional keyword arguments (detected via `inspect.signature()`):
- `progress` — callable for real-time status updates
- `tz` — IANA timezone string for localized output

Malformed plugins are skipped with a stderr warning, not a crash.
Partial plugin failure (some succeed, some raise) exits 0.
All matched plugins fail → exits non-zero.

### Error Reporting (Sentry)

Plugins are defensive — they catch their own failures (API/subprocess/file errors)
and return a friendly `{"text": ...}` message instead of raising. That means the
pipeline never sees the exception, so **errors are invisible to Sentry unless the
plugin reports them explicitly.**

When you catch a *genuine failure* (not control-flow fallback) and turn it into a
friendly message, also report it:

```python
from sandy.observability import capture

try:
    result = some_api_call()
except Exception as e:
    capture(e, plugin="myplugin", stage="fetch")  # tags aid filtering in Sentry
    return {"text": f"Couldn't reach the service: {e}"}
```

`capture()` is a no-op when Sentry isn't initialized (CLI mode, local dev, DEBUG),
so it's always safe to call. Do **not** instrument typed control-flow excepts that
are expected fallbacks (e.g. `ZoneInfoNotFoundError` → default tz, `ValueError`
while parsing) — those would just create noise. Raised exceptions that propagate to
the pipeline are captured automatically.

### CLI Wrapper Pattern

Plugins that wrap sibling CLI tools (estimatedtaxes, itguy) follow a common pattern:
- `shutil.which()` to check availability
- `subprocess.run()` with `capture_output=True, text=True, timeout=30`
- Friendly fallback message when the tool isn't on PATH
- Env vars flow from `sandy.toml` → `os.environ` → inherited by subprocess
- On unexpected failure (non-zero exit, timeout), `capture()` it before returning
  the friendly message — see **Error Reporting** above

## Transport Plugin Contract

Each transport is a `.py` file in `sandy/transports/` that exposes:

- `name: str` — transport identifier (e.g. `"slack"`)
- `async listen(callback)` — start listening, call `callback(text, actor, reply_fn, tz=tz)` for each message
- `format_response(plugin_name: str, response: dict) -> Any` — translate response dict to channel format

## Configuration

Sandy reads config from `~/.config/sandy/sandy.toml` (preferred) or `./sandy.toml` (dev).

Convention: **UPPERCASE** keys are environment variables (injected into `os.environ` by
`apply_env()` before plugins run). Lowercase keys are Sandy configuration.

```toml
# Global env vars
SANDY_PRINTER = "Brother_MFC_L2750DW_series"

# Plugin sections
[estimatedtaxes]
ATEAM_EMAIL = "..."
ATEAM_PASSWORD = "..."

[spotify]
active = "yes"
SPOTIPY_CLIENT_ID = "..."

# Daemon config
[daemon]
transports = ["slack"]
log_level = "DEBUG"

[sandy]
timezone = "America/New_York"
```

Plugin activation: any plugin can be disabled with `active = no` in its section.

## Daemon Mode

`sandy serve` starts the daemon as a systemd user service on the homelab.
Loads all plugins once, listens on configured transports.

Deployment: `deploy/install.sh` sets up the systemd service; `restart.sh` is the
post-pull hook for `itguy deploy sandy`.

## Current Plugins

- **spotify** — new releases from followed artists (`"find me new music"`, `"new music"`)
- **music_discovery** — Last.fm → similar artists → Spotify playlist (`"find me new music"`, `"discover music"`)
- **cryptics** — random cryptic crossword, sent to printer (`"crossword"`)
- **hardcover** — library book suggestion from Want to Read list (`"suggest a library book"`, `"library book"`)
- **sports** — today's schedule + live scores: Red Sox, Patriots, Celtics, Bruins, Everton (`"sports"`, `"game today"`, `"scores"`)
- **real_men** — Bud Light Real Men of Genius audio clips (`"real man"`, `"real men"`)
- **cast_to_tv** — Chromecast/Google TV control (`"cast to tv"`, `"stop casting"`)
- **youtube_tv** — YouTube TV channel tuning via ADB (`"watch "`, `"tune to "`, `"put on "`)
- **dispatch** — Dispatch automation status from Obsidian files (`"dispatch status"`, `"status"`)
- **estimatedtaxes** — tax queries via `estimatedtaxes` CLI (`"tax summary"`, `"tax list"`, `"tax sync"`)
- **itguy** — homelab deployment via `itguy` CLI (`"itguy list"`, `"itguy deploy"`, `"itguy force"`)
- **health** — list active plugins and commands (`"health"`)

### Transports

- **slack** (`sandy/transports/slack.py`): Socket Mode, Block Kit formatting, DMs + @mentions
  - Requires `SLACK_APP_TOKEN` and `SLACK_BOT_TOKEN` in `sandy.toml`

## Development

```bash
uv pip install -e .       # install in dev mode
uv run pytest -v          # run all tests
uv run sandy "find me new music"
uv run sandy serve        # start daemon locally
```

Always use `uv`, never `pip`.

## Testing

- 351+ tests, 80% coverage gate enforced via pytest-cov
- All external API calls mocked (`unittest.mock`)
- Plugin-specific test files in `tests/` (e.g. `test_spotify.py`, `test_estimatedtaxes_plugin.py`)
- Pre-commit hooks: ruff lint + format

## Conventions

- Do all work in a `claude/` branch
- Python 3.13+
- Prefer stateless solutions
- Plugin discovery is alphabetical by filename
- Timezone: UTC in code/logs; user-facing output uses `tz` param when available
