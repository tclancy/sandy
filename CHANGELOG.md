# Sandy Changelog

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
