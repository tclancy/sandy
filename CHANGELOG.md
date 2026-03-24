# Sandy Changelog

## 2026-03-24

- Add `music_discovery` plugin: Last.fm top artists (3mo) → similar artists → top tracks → Spotify playlist populate (issue #29)
- Add `pylast>=7.0.2` dependency
- Deactivate `spotify` plugin in sandy.toml.example (replaced by music_discovery)
- 212 tests passing, 82% coverage

## 2026-03-21

- Add no-match fallback: daemon replies "Sorry, I'm not sure how to do that." when no plugins match (issue #27)
- Add `QueueProgressReporter` in `sandy/progress.py`: thread-safe progress reporter for daemon transports using `asyncio.Queue` + `call_soon_threadsafe` — real-time progress messages while pipeline runs in thread (issue #27)
- Add `SandyPlugin` base class in `sandy/plugins/base.py`: optional ABC with default `handle_async()` that wraps sync `handle()` via `asyncio.to_thread` — enables gradual async migration without breaking existing plugins (issue #27)
- 193 tests passing

## 2026-03-18

- Resolved merge conflicts on `claude/plugin-feedback-8` (PR #15) by rebasing onto main
- Merged daemon mode (PR #14) changes with progress reporting changes: cli.py uses `progress_factory`, pipeline.py adds `_accepts_progress` + progress_factory parameter, spotify.py keeps dict format + adds progress calls
- 132 tests passing, 83% coverage

## 2026-03-17

- Replace `_format_text` if-chain with `_FIELD_FORMATTERS` dynamic dispatch registry — new response field types require only a new `_format_{key}` function and registry entry, no edits to the renderer; outer function renamed to `_render_response` (issue #16, PR #17)
- Add plugin progress reporting system (`sandy/progress.py`, `sandy/pipeline.py`)
- Plugins can opt in to progress callbacks via `handle(text, actor, progress=None)` — backward compatible
- `CliProgressReporter` writes per-plugin status to stderr, overwriting the same line; stdout stays clean
- CLI refactored to delegate to `run_pipeline()` with progress factory
- `spotify` plugin updated to report per-artist progress during API calls
- 16 new tests; 115 total passing

## 2026-03-16

- Add TOML configuration file support (`sandy/config.py`); reads `~/.config/sandy/sandy.toml`
- UPPERCASE keys in config are injected as env vars; plugins respect `active = yes/no`
- Add `sandy.toml.example` and `docs/plugins/config.md`
- Add Real Men of Genius plugin: `sandy "tell me about a real man"` plays a random mp3
- Add Hardcover library suggestion plugin: `sandy "suggest a library book"` picks from In Dover × Want to Read

## 2026-03-19
- Add sports schedule plugin: returns next game (within 14 days) for Red Sox, Patriots, Celtics, Bruins, Everton; ESPN API for US sports, football-data.org for Everton (issue #6, PR #23)
- Extract printer to sandy/printer.py; add pdf_url output field to CLI formatter so any plugin can trigger printing by returning pdf_url; simplify cryptics plugin (issue #18, PR #24)
