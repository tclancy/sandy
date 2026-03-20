# Sandy

A personal automation tool that routes text commands to plugins. Inspired by
[I Want Sandy](https://boingboing.net/2007/11/14/i-want-sandy-perfect.html) — the
idea that you should be able to send a casual message and have something useful
happen on the other end.

Send Sandy a command from the CLI or via Slack, and the matching plugin(s)
respond with links, audio, a printed PDF, or whatever else makes sense.

---

## Quick Start

**Requirements**: Python 3.13+, [uv](https://github.com/astral-sh/uv)

```bash
# Clone and enter the project
git clone https://github.com/tclancy/sandy
cd sandy

# Copy and edit the config file
cp sandy.toml.example ~/.config/sandy/sandy.toml
# Fill in API keys for the plugins you want to use

# Run a command
uv run sandy "crossword"
uv run sandy "find me new music"
uv run sandy "suggest a library book"
```

Or use the wrapper script on your PATH:

```bash
ln -s /path/to/sandy/sandy.sh /usr/local/bin/sandy
sandy "crossword"
```

---

## Configuration

Sandy uses a TOML config file. It looks for it in this order:

1. `~/.config/sandy/sandy.toml` — recommended (keeps secrets out of the project)
2. `./sandy.toml` — project root, useful for local dev

Copy the example to get started:

```bash
cp sandy.toml.example ~/.config/sandy/sandy.toml
```

**Convention**: `UPPERCASE` keys are environment variables (API keys, tokens).
`lowercase` keys are Sandy configuration (`active = yes/no`).

To disable a plugin without removing it: set `active = no` in its config section.

---

## CLI Usage

```
usage: sandy [--actor NAME] <text>

positional arguments:
  text          The command text to process

options:
  --actor NAME  Who is sending the command (default: tom)
```

**Examples:**

```bash
# Get today's cryptic crossword links
sandy "crossword"

# Find recent Spotify releases from artists you follow
sandy "find me new music"

# Get today's sports schedule
sandy "sports"

# Sandy as another user
sandy --actor michelle "crossword"
```

If no plugin matches the command, Sandy responds: `I don't know how to do that yet.`

---

## Running as a Slack Bot

Sandy can run as a Slack daemon that listens for direct messages or `@sandy`
mentions and routes them through the same plugin pipeline.

**Setup:**

1. Create a Slack app at https://api.slack.com/apps with Socket Mode enabled
2. Add `SLACK_APP_TOKEN` (xapp-...) and `SLACK_BOT_TOKEN` (xoxb-...) to your
   `~/.config/sandy/sandy.toml`
3. Start the daemon:

```bash
sandy serve
# or:
uv run sandy serve
```

The bot processes any message in a DM or `@sandy` mention, runs it through the
plugin pipeline, and replies in-thread.

---

## Plugins

Each plugin declares the text commands it handles. Commands are matched
case-insensitively. If multiple plugins match, all of them respond.

| Plugin | Commands | Requires |
|--------|----------|----------|
| **cryptics** | `crossword` | None — fetches from public archives |
| **spotify** | `find me new music`, `new music` | Spotify API credentials |
| **hardcover** | `suggest a library book`, `library book`, `suggest a book` | Hardcover API key |
| **sports** | `sports` | `FOOTBALL_DATA_API_KEY` for Premier League; others are free |
| **real_men** | `real men of genius` | None |

### cryptics

Pulls a random cryptic crossword from the Hex (Cox & Rathvon) archive and the
latest Mad Dog Cryptics puzzle. Returns links and, if a printer is configured,
sends the PDF to your local printer.

```toml
[cryptics]
active = yes
# SANDY_PRINTER = "Brother_MFC_L2750DW_series"  # run `lpstat -p` to find yours
```

### spotify

Finds albums released in the last 30 days by artists you follow.

```toml
[spotify]
active = yes
SPOTIPY_CLIENT_ID     = "your-client-id"
SPOTIPY_CLIENT_SECRET = "your-client-secret"
SPOTIPY_REDIRECT_URI  = "http://127.0.0.1:8888/callback"
```

First run will open a browser for OAuth. Token is cached locally.

### hardcover

Picks a random book from your Hardcover "In Dover" list that's also on your
"Want to Read" shelf, then generates a Dover Public Library catalog search link.

```toml
[hardcover]
active = yes
HARDCOVER_API_KEY = "your-hardcover-api-key"
```

### sports

Returns today's schedule for: Red Sox, Celtics, Bruins, Patriots (ESPN),
Everton (football-data.org).

```toml
[sports]
active = yes
FOOTBALL_DATA_API_KEY = "your-key"  # free at football-data.org
```

### real_men

Plays a random "Real Men of Genius" Bud Light ad audio clip via `afplay` (macOS).

---

## Writing a Plugin

A plugin is a Python module in `sandy/plugins/`. It needs three things:

```python
# sandy/plugins/myplugin.py

name = "myplugin"                       # plugin identifier
commands = ["do the thing", "thing"]    # matched case-insensitively

def handle(text: str, actor: str, progress=None) -> dict:
    """Return a response dict. Keys control how output is rendered."""
    return {
        "title": "My Plugin",
        "text": "Here's what I found.",
        "links": [{"label": "Example", "url": "https://example.com"}],
    }
```

**Response dict keys** (all optional):

| Key | Type | Effect |
|-----|------|--------|
| `title` | str | Printed as a header |
| `text` | str | Plain text body |
| `links` | list of `{label, url}` | Printed as labeled URLs |
| `audio_url` | str | Downloaded and played via `afplay` (macOS) |
| `pdf_url` | str | Downloaded and sent to the configured printer |

The `progress` parameter (optional) is a callable you can use to report status:

```python
def handle(text: str, actor: str, progress=None) -> dict:
    if progress:
        progress("Fetching data...")
    # ...
```

Add a config section to `sandy.toml.example` for any API keys your plugin needs.

---

## Development

```bash
# Install dev dependencies
uv sync --all-groups

# Run tests
uv run pytest

# Lint and format
uv run ruff check --fix .
uv run ruff format .

# Pre-commit hooks (run automatically on commit)
pre-commit install
```

Tests live in `tests/`. The `conftest.py` has shared fixtures. Coverage gate is 80%.

---

## Project Structure

```
sandy/
├── sandy/
│   ├── cli.py            # Entry point, output formatting
│   ├── pipeline.py       # Plugin loading, matching, execution
│   ├── config.py         # Config file parsing, env var injection
│   ├── loader.py         # Dynamic plugin discovery
│   ├── matcher.py        # Text-to-plugin matching
│   ├── progress.py       # Progress reporting for CLI
│   ├── printer.py        # PDF printing support
│   ├── daemon.py         # Slack bot server
│   ├── transport_loader.py  # Transport plugin loader
│   ├── plugins/          # Built-in plugins
│   └── transports/       # Transport backends (Slack)
├── tests/                # Test suite
├── sandy.toml.example    # Config template
├── sandy.sh              # PATH-friendly wrapper script
└── pyproject.toml
```
