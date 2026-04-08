# Sandy Changelog

## 2026-04-07
- Feat #84: plugin error messages now surface in Slack — daemon appends `str(e)[:100]` in backticks to the generic friendly error; empty-exception case handled cleanly; 335 tests, 85.9% coverage

## 2026-04-04
- Fix: CI failure on PR #76 — removed local-path dev deps (`../irs`, `../itguy`) from pyproject.toml that broke `uv sync` in GitHub Actions; deleted duplicate plugin test files (tests live in their packages); added matcher integration test to preserve coverage; 332 tests, 85.5% coverage

## 2026-04-03
- Feat #72: itguy plugin adds `itguy status`, `itguy status <svc>`, `itguy disk` commands — status and disk output wrapped in Slack code blocks for monospace rendering; 365 tests passing
- Feat #74: live-reload for plugin directory — daemon polls every 2s, reloads on file add/remove/modify; follows symlinks via stat(); keeps old plugins active if a broken file causes reload failure
- Feat: estimatedtaxes plugin `tax summary` now uses `--format slack` (PR #70) — returns Slack monospace code block with aligned columns instead of raw CLI text; 354 tests passing

## 2026-04-02

- Fix #65: detect linger state before enabling (PR #67) — `loginctl show-user` check before `loginctl enable-linger` avoids pkttyagent error on headless systems without polkit; updated fallback hint to `sudo loginctl enable-linger`
- Feat #61: systemd user service (PR #63) — `deploy/sandy.service`, `deploy/install.sh`, `restart.sh`; Sandy runs natively as a systemd user service; restart.sh is post-pull hook for itguy git-pull deploys
- Feat #62: estimatedtaxes plugin (PR #64) — `tax summary`, `tax list`; read-only; 16 new tests (351 total)
- Feat #59: IT Guy plugin (PR #60) — `itguy list`, `itguy deploy <svc>`, `itguy force <svc>` commands; graceful fallback when itguy not on PATH; 18 new tests

## 2026-03-31

- Fix #55: printer IPP URI support for Linux homelab (PR #58) — `SANDY_PRINTER = "ipp://ip/ipp/print"` bypasses CUPS mDNS; failure now includes stderr + lpstat diagnostics in Slack message
- Fix #54: sports plugin Slack display (PR #57) — single `*` for bold, ESPN dict score → displayValue, title → "Hey there, sports fans!"
- Chore: add `.envrc.example` + `.envrc` to `.gitignore` (PR #56)

## 2026-03-30

- Feat #49/#50: timezone awareness end-to-end (PR #51)
  - `--timezone`/`-z` CLI flag passes IANA tz name to pipeline
  - `sports` plugin: `_to_tz()` helper, game times shown in requested tz; falls back to config `[sandy] timezone`, then system tz
  - `spotify` plugin: opts in to tz pipeline (no display dates currently, ready for future)
  - `daemon`: tz threaded through `handle_message()` and `_handle_callback()`
  - Slack transport: fetches `user.tz` from `users.info` API (cached per user ID), Slack users automatically get times in their own timezone
  - No new dependencies (stdlib `zoneinfo`, Python 3.13+)
  - 11 new tests; 309 total, 85% coverage

## 2026-03-28

- Fix #47: dispatch plugin disabled by default in sandy.toml.example — only useful when Sandy runs on the same Mac as metaframework; health plugin now respects `active = "no"` and skips disabled plugins (PR #48)

## 2026-03-27

- Fix #41: printing from Slack did not work — root cause was Slack transport's format_response() silently ignoring pdf_url; daemon now calls print_pdf() before dispatching to transport, with failure message if printer unreachable (PR #46)
- Fix #42: dispatch plugin broken on homelab — added `_remote_context()` detection; plugin re-enabled in Ansible template with graceful fallbacks when Mac files are unavailable
- Rename `inbox`/`dispatch inbox` commands to `pm`/`dispatch pm` (PR #43)
- Feat #40: sports plugin now shows today's results and live scores as a top section — reuses existing ESPN schedule data for US sports; separate date-filtered call for Everton via football-data.org; added `scores` command alias

## 2026-03-25

- Add `youtube_tv` plugin — "watch ESPN", "tune to CNN", "put on NBC Sports" tunes Google TV via ADB deeplinks (PR #37, closes #32)
- Hardcoded channel code table (~30 channels: sports, news, network, entertainment, kids)
- Config: YOUTUBE_TV_ADB_HOST (required), YOUTUBE_TV_ADB_PORT, YOUTUBE_TV_ADB_PATH
- 32 new tests; 273 total, 83% coverage

## 2026-03-25

- Fix #34: dispatch plugin `sys.modules[__name__]` KeyError — all "status"/"check"/"inbox" commands now work; root cause was dynamic loader not registering modules in sys.modules
- Fix #35: plugin errors now return friendly "I am terribly sorry, X just does not want to behave!" to Slack users; technical details still logged + shown on CLI stderr
- Feat #33: new `health` built-in command — lists all active plugins and their commands (PR #36)
- 241 tests, 82% coverage

## 2026-03-25

- Add `cast_to_tv` plugin — "cast to tv \<url\>", "cast this \<url\>", "stop casting" (PR #31, closes #7)
- MIME type detection from URL extension; defaults to video/mp4
- Configurable target device (CAST_DEVICE_NAME) and discovery timeout (CAST_TIMEOUT)
- Add pychromecast>=14.0 as project dependency
- 22 new tests (all pychromecast calls mocked); 215 total tests, 83% coverage

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
