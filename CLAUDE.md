# Sandy — Claude Code Configuration

## What Is Sandy

Sandy is a CLI tool and Slack bot that routes freeform text commands to plugins.
Named for [I Want Sandy](https://boingboing.net/2007/11/14/i-want-sandy-perfect.html)
(2007). The goal is to "bring delight" — surfacing things you care about with
minimal friction. **Read the Inspiration section below before writing any
user-facing string.**

Fan-out model: **all** matching plugins respond to a command, not just the first match.

## Inspiration — why Sandy is called Sandy

The name comes from **I Want Sandy**, a 2007 virtual assistant you used by
sending it email in plain English: *"Sandy, remind me to pick up the dry
cleaning at 6:50pm tonight."* It shut down in 2008 and people still miss it.
Eugene Wei's [write-up of why](https://www.eugenewei.com/blog/2014/1/7/i-want-sandy)
is the design brief for this project — read it once; it is short.

Three things from that post are load-bearing here, in descending order of how
often they get forgotten:

**1. Tiny flourishes go a long way.** Wei's example is the whole thesis:

> One time I recall sending IWantSandy an email at 3 in the morning asking
> "her" to remind me of something the next morning. Her reply began with
> "Wow! You're up late! Get some sleep soon" or something like that. Simple to
> code, powerfully effective.

That is one `if` statement on an hour. It is also the single most memorable
thing anyone wrote about the product, seven years after it died. When you are
choosing between a correct string and a human one, the human one is the
product.

**2. The most efficient way to do something is not always the most human.**
Email was a *worse* interface than a form — you had to wait for a reply, and
you had to re-send when Sandy misunderstood. It was better anyway, because
"interacting with it in a manner typically reserved for interacting with other
humans created a powerful illusion of intimacy". This is why Sandy takes
freeform text and substring-matches it rather than exposing subcommands and
flags, and why a misunderstanding should ask for clarification rather than
print a usage block.

**3. Let people turn it off.** Wei, in the same post: "I know some folks would
hate that type of false anthropomorphism, but perhaps you could choose whether
to turn it on or off." Every flourish ships with a switch — see
`[sandy] flourishes` in `sandy.toml.example`.

### What this means when you write a string

| Instead of | Say |
|------------|-----|
| `Unknown command: 'wibble'` | `I'm not sure what to do with "wibble". Ask me for help and I'll show you what I know.` |
| `ERROR: plugin raised RuntimeError` | `I am terribly sorry, cryptics just does not want to behave!` |
| `Playlist updated (23 tracks)` | `Saved 23 tracks to 'Discovery'.` — say what *you did*, not what changed |
| Silence on interrupt | `Wrapping up early today!` (`cli.py` already does this — copy that register) |

Sandy talks like a capable assistant who is slightly amused by the job. Warm,
brief, first person, never cute for its own sake, and never emoji-as-tone.

### The one hard rule: asides live at the boundary, not in plugins

Sandy fans out — **all** matching plugins answer a single command. So anything
that belongs to the *interaction* rather than the *answer* must be emitted once,
at the delivery boundary (`cli.main`, `daemon._handle_callback`), never from
inside a plugin's `handle()`. A friendly greeting written into a plugin repeats
itself once per match the first time two plugins match the same phrase.

`sandy/voice.py` owns this. It exposes:

- `opening_aside(actor, tz=, config=)` — the once-per-interaction aside, or
  `None` when the hour is unremarkable. **The silence is the feature**: a
  greeting on every command is a template, and a template reads as software.
  Sandy speaks up in the small hours (23:00–04:59) and early (05:00–06:59) and
  says nothing the rest of the day.
- `prepend_aside(response, aside)` — attaches it to the first thing Sandy says.
- `did_not_understand(text)` — the shared "ask me to clarify" reply, so CLI and
  Slack cannot drift apart on the same condition (they had, before #183).

Plugins must not import `sandy.voice`.

**Testing note:** `opening_aside` reads the wall clock, so `tests/conftest.py`
carries an autouse fixture that silences it. A test that needs the real thing
carries `@pytest.mark.real_voice`; a boundary test that wants a fixed aside
patches `voice.opening_aside` directly. Without that fixture, any test pinning
an exact reply string passes at 2 p.m. and fails at 3 a.m.

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
- **voice.py** — once-per-interaction flourishes and the shared didn't-understand
  reply; called only from the delivery boundary, never from a plugin (see Inspiration)

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
- **dispatch** — Dispatch automation status via dispatchd's HMAC-signed HTTP API (`"dispatch status"`, `"dispatch check"`, `"dispatch pm"`)
- **estimatedtaxes** — tax queries via `estimatedtaxes` CLI (`"tax summary"`, `"tax list"`, `"tax sync"`)
- **itguy** — homelab deployment via `itguy` CLI (`"itguy list"`, `"itguy deploy"`, `"itguy force"`)
- **help** — list active plugins and commands (`"help"`); prefix-matched so it only fires when help is the primary intent

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
