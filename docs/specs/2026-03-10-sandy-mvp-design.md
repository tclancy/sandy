# Sandy MVP Design

**Date:** 2026-03-10
**Status:** Approved

## Overview

Sandy is a CLI tool that routes freeform text commands to plugins. Inspired by [I Want Sandy](https://boingboing.net/2007/11/14/i-want-sandy-perfect.html), it aims to abstract away busywork by letting you type what you want done and having the right plugin handle it.

## Architecture

```
User -> CLI (sandy "some text") -> Plugin Loader -> Pattern Matcher -> Plugin.handle() -> stdout
```

No daemon, no server, no database. A single Python package installed locally via `uv pip install -e .` so `sandy` is available as a shell command.

## Plugin Contract

Each plugin is a `.py` file in `sandy/plugins/` that exposes:

- `name: str` — human-readable name (e.g. `"spotify"`)
- `commands: list[str]` — phrases to match against, treated as case-insensitive substring matches (not regex)
- `handle(text: str, actor: str) -> str` — receives full input text and who sent it, returns response string. `actor` identifies the user (defaults to `"tom"`). Plugins may ignore it for now but it's there for multi-user support later.

### Plugin Loader Behavior

1. Walks `sandy/plugins/`, imports every `.py` file that isn't `__init__.py`
2. Validates each has `name`, `commands`, `handle`
3. Malformed plugins are skipped with a warning to stderr, not a crash

### Matching (`matcher.py`)

`matcher.py` owns the matching logic, exposed as `find_match(text, plugins) -> plugin | None`. `loader.py` is responsible only for discovery and validation.

1. Iterates plugins in alphabetical order **by filename**
2. Checks each command phrase against input (case-insensitive substring match)
3. First match wins, calls `handle()`, prints result
4. No match prints: `"I don't know how to do that yet."`

### Error Handling

If a matched plugin's `handle()` raises an exception at runtime, the CLI catches it, prints a friendly error message to stderr (e.g. `"spotify plugin failed: <error>"`), and exits with a non-zero status. It does not fall through to try other plugins.

## First Plugin: Spotify

- **Commands:** `["find me new music", "new music"]`
- **Behavior:** Pulls Release Radar playlist via Spotify API, returns formatted list of artist / album / track with links
- **Auth:** Spotify OAuth requires a user-scoped token (Release Radar is a personalized playlist). Setup: register a Spotify developer app, run `spotipy`'s one-time auth flow to get a refresh token, store credentials in environment variables (`SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, `SPOTIPY_REDIRECT_URI`). `spotipy` handles token refresh and caching automatically. Plugin fails gracefully with a clear error if auth is missing or broken.
- **Dependency:** `spotipy`

### Example Output

```
New music from Release Radar:
- Artist - Album - Track (link)
- Artist - Album - Track (link)
```

## Project Structure

```
sandy/
├── pyproject.toml          # uv-managed, script entry point for `sandy`
├── sandy/
│   ├── __init__.py
│   ├── cli.py              # entry point
│   ├── loader.py           # plugin discovery + validation
│   ├── matcher.py          # pattern matching logic
│   └── plugins/
│       ├── __init__.py
│       └── spotify.py
└── tests/
    ├── test_loader.py
    ├── test_matcher.py
    └── test_cli.py
```

- **uv** for dependency management
- **pytest** for tests
- Tests cover: plugin loading, pattern matching, CLI end-to-end (with mock plugin), malformed plugin handling

## CLI Interface

```
sandy "find me new music"
sandy --actor michelle "find me new music"
```

Actor defaults to `"tom"`.

## Out of Scope

- No daemon / persistent process
- No Slack, email, or any input channel beyond CLI
- No AI / LLM processing
- No state / database
- No config file
- No plugin dependencies on each other
- No user authentication (actor is a CLI flag string)
- No packaging for distribution
