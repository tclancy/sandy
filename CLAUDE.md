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
  → loader.py (discovers + validates plugins from sandy/plugins/)
  → matcher.py (case-insensitive substring match, returns ALL matches)
  → each matching plugin's handle(text, actor) → stdout
```

No daemon. No server. No database. Stateless by design.

## Plugin Contract

Each plugin is a `.py` file in `sandy/plugins/` that exposes:

- `name: str` — human-readable name (e.g. `"spotify"`)
- `commands: list[str]` — phrases to match (case-insensitive substring)
- `handle(text: str, actor: str) -> str` — returns response string

Malformed plugins are skipped with a stderr warning, not a crash.
Partial plugin failure (some succeed, some raise) exits 0.
All matched plugins fail → exits non-zero.

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
