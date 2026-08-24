# Sandy Changelog

## 2026-08-24
- Feat #183: Sandy has a voice. `CLAUDE.md` gains an **Inspiration** section recording where the name comes from — Eugene Wei's [I Want Sandy](https://www.eugenewei.com/blog/2014/1/7/i-want-sandy) — and turning it into rules an agent can follow rather than background colour: tiny flourishes over correct-but-flat strings, freeform text over subcommands, and a switch on every flourish because Wei asked for one.
- `sandy/voice.py` implements the one concrete example from that post: a reply in the small hours that opens by remarking on the hour. **The silence is the feature** — Sandy speaks up 23:00–04:59 and 05:00–06:59 and says nothing at 2pm, because a greeting on every command is a template and a template reads as software. The window is read in the requesting user's zone (Slack per-user `tz` → `[sandy] timezone` → the machine's clock), and `[sandy] flourishes = "no"` switches it off.
- The aside is emitted **once per interaction, at the delivery boundary** — never from inside a plugin. Sandy fans out, so a greeting written into `handle()` repeats once per match. It travels as its own `aside` response field rather than as a prefix on `text`: prefixing defeated the #122 code-fence auto-promotion (whose regex is anchored at the start of `text`), rendered the greeting below the header block, and spent the 3000-character Slack section budget on a pleasantry. The Slack transport renders it as a leading section; the CLI prints it as its own line.
- The unmatched-command reply is now one string for both surfaces, and it echoes what you said instead of shrugging: `I'm not sure what to do with "wibble". Ask me for `help` and I'll show you what I know.` CLI previously said *"I don't know how to do that yet."* and the daemon *"Sorry, I'm not sure how to do that."* — same condition, two voices. Slack control syntax in the echo (`<!channel>`, `<@U123>`) is defused so Sandy can't ping a channel to announce she didn't understand.
- Fix: a plugin's `progress()` message could be delivered to nobody. It is queued from the executor thread via `call_soon_threadsafe`, and the end-of-pipeline sentinel was posted without first letting that callback run — so the drain task could see `None` first and exit. Pre-existing; no test covered the path until #183 added one, which then failed on Linux/CPython 3.13.15 while passing on macOS/3.13.7.
- `daemon._handle_callback` split into `_run_with_progress` / `_deliver` / `_error_reply` (the repo's C901 gate fired at complexity 12). `tests/conftest.py` silences the voice by default — two existing daemon tests pinned exact reply strings and would otherwise have passed at 2pm and failed at 3am; opt back in with `@pytest.mark.real_voice`. A new test in `test_plugins_base.py` enforces the no-`sandy.voice`-in-plugins rule rather than leaving it as prose.

## 2026-07-28
- Feat #137 (Part A): `dispatch shift <kind>` — triggers a Mac-side shift from Slack via `POST /v1/dispatch/shift`, whose server half merged on 2026-07-13 as metaframework#382 and had been unwired since. Kinds are `night`, `day`, `wrapup`, `pmreview`, `sanity`, `selffix`. Needs the `shift` capability on the dispatchd key, which is deliberately not implied by `work` — the 403 copy names `shift` specifically so it points at the right line of `keys.toml`. Success copy follows Part C's rule and says *spawned*, never *running* (meta#438), and the 409 never claims a global mutex.
- The POST plumbing shared with `dispatch work` is now extracted (`_WriteCommand` + `_post_command`), so the Sentry policy — capture 5xx, treat 4xx as ordinary control flow — and the error-code lookup are decided once for both commands rather than duplicated.
- `slot` is hardcoded to `null`, and that is a workaround rather than a simplification. dispatchd appends a non-null slot to the child's argv, but `dispatch`'s top-level parser takes exactly one positional, so `dispatch dayshift 9am` exits 2 — *after* the endpoint has returned 202 with a run id and written a `running` registry row. Any slot value would therefore produce a shift that reports as spawned and never runs. Filed as metaframework#450; a regression test pins the whole payload so a slot cannot creep back in.
- The kind vocabulary is deliberately *not* validated client-side, unlike the URL shape in `dispatch work`. A GitHub URL is a shape and shapes don't drift; a shift kind is membership in a server-owned enum that does. dispatchd's 400 already lists the valid set, so it is echoed straight through and a kind added server-side works here with no change. That also means the kind must reach the server byte-accurate — parsing it through `matcher.normalize` would delete the hyphen from `pm-review` and produce a 400 quoting a string the user never typed, so the argument gets a gentler tidy that strips only polite framing and trailing punctuation.

## 2026-07-27
- Feat #137 (Part C): `dispatch work <github issue or PR URL>` — Sandy's first write command. Posts the URL to `POST /v1/dispatch/work` (metaframework #435) over the same HMAC transport as the read commands, and reports the 202 handshake back into Slack. Gated twice: `default_access = "private"` keeps it owner-only, and server-side it needs the `work` capability, which is deliberately not implied by `read` or `shift`. All six of dispatchd's machine error codes (`bad_request`, `forbidden`, `forbidden_owner`, `forbidden_path`, `repo_not_found`, `conflict`) map to a message that names the actual fix, keyed on the code rather than the HTTP status because 403 alone covers three different remedies. URLs are canonicalized client-side (scheme forced to https, `www.` dropped, owner/repo lowercased, `#issuecomment-N` fragment and query string stripped) so the target dispatchd checked is the one the agent re-parses, and an unworkable paste is refused locally instead of burning a signed round trip.
- Per meta#438, the success message says *spawned*, never *running*: dispatchd's in-flight registry only sees runs its own endpoints started, so a 202 during a launchd-started shift is real and the child then loses the `LockManager` race. The reply points at `dispatch check` for the confirmation the 202 cannot give.
- Fix: a Slack link whose display text contains spaces (`<url|sandy issue 137>`) was truncated at the label's first space and rejected as a bad URL. The angle-bracket unwrap now runs against the whole message remainder before any whitespace split. Only the half before the `|` is trusted as the destination — display text is attacker-controlled and can claim to be a github.com issue while pointing elsewhere.

## 2026-07-14
- Fix: dispatch plugin sends `User-Agent: dispatch-sandy/1.0` — Cloudflare's Browser Integrity Check (error 1010) blocked the default `Python-urllib` UA at the tunnel before requests reached dispatchd, surfacing as a mystery 403 on every signed call. Found during the first homelab→Mac end-to-end deploy of #136; naming follows the `dispatch-[app]` convention from `dispatchd-mcp/1.0` (metaframework, 2026-07-07, same CF issue).
- Feat #136: dispatch plugin talks to dispatchd over HTTP with HMAC-SHA256 request signing — `dispatch status` / `check` / `pm` hit the `/v1/*` read surface so homelab Sandy no longer needs Mac filesystem access. Per review, the local-file fallback was removed entirely: dispatchd is the single backend, and an unconfigured plugin (missing any of `DISPATCHD_BASE_URL` / `DISPATCHD_KEY_ID` / `DISPATCHD_SECRET`) returns a friendly setup message. The three per-command HTTP functions collapsed into one registry-driven dispatcher; wire shapes are typed (`Envelope` / `InFlightRow` TypedDicts); HTTP failures are reported to Sentry via `observability.capture()` (tagged `plugin=dispatch`, `stage=<endpoint>`). Multi-angle pre-push review then caught: in-flight run kind read from the wrong key (`session_type`/`mode` → dispatchd actually sends `shift`), HMAC headers forwarded on cross-host redirects (redirects now refused), malformed 200 responses escaping the friendly-error path, post-connect timeouts misclassified, and a silent first-20-lines truncation.

## 2026-07-13
- Fix #139: `help` plugin is context-aware — no longer fires when help is a subcommand flag (e.g. `itguy logs --help`). New `match_mode = "prefix"` in `sandy/matcher.py` restricts a plugin's substring match to the leading intent; only `help` opts in. Retired the `health` alias (pre-#96 shim, no callers left).

## 2026-06-30
- Fix #129: Sentry stayed silent for ~2 months despite visible failures. Root cause: the *only* path that reached Sentry was an unhandled plugin exception (caught by the pipeline) or a hard crash — but Sandy's plugins are defensive and catch their own failures, returning friendly text instead of raising, so nothing was ever reported. New `sandy/observability.py` centralizes init (`init_sentry`) and adds an explicit `capture()` helper (no-op when Sentry is off). The pipeline now explicitly `capture()`s caught plugin errors (tagged with the plugin name), and plugins that swallow failures into friendly messages (cryptics, spotify, sports ESPN/football-data, music_discovery) now report them too. Logging→event auto-capture is disabled (`LoggingIntegration(event_level=None)`) so every Sentry event is explicit and tagged — no duplicates. `sandy serve` logs Sentry status at startup. (462 tests, 86% coverage)

## 2026-04-16
- Feat #96: Actor model enforcement — identity resolution (`actors.py`), plugin-level permissions (public/private/allowed_actors), system-level action caps (print, cast). Unknown actors get "I don't know you" message. Cryptics omits print without cap; cast_to_tv rejects without cap. Backward compatible: no config = no enforcement. (411 tests, 86% coverage)
- Feat #96: Renamed health plugin to help — backward-compat `health` command still works. Help output filtered by actor permissions.
- Fix #104: cryptics PDF downloads — Cox & Rathvon `/pdf` endpoint now uses `?download=true` for raw file; Mad Dog Dropbox URLs rewritten from `dl=0` to `dl=1` for direct download instead of HTML preview (PR #105, 12 cryptics tests pass)

## 2026-04-15
- Feat #101: `music login` Slack command — generates Spotify authorization URL with CSRF state token, sends via Slack; user clicks to re-auth; Sandy's new aiohttp OAuth callback server (port 8888, `OAUTH_SERVER_PORT`) handles the redirect and exchanges the code for a token automatically; CSRF state validated on callback; error responses HTML-escaped (XSS-safe); 387 tests, 85% coverage (PR #103)
- Feat #101: `sandy/oauth_server.py` — aiohttp HTTP server running as asyncio task alongside Slack transport; `/callback` for Spotify OAuth, `/health` for tunnel verification; started by daemon when `OAUTH_SERVER_PORT` env var is set
- Config: `sandy.toml.example` updated with `OAUTH_SERVER_PORT` and correct Cloudflare redirect URI; homelab `vars.yml` updated (`sandy.tomclancy.info/callback` redirect URI, port 8888); `sandy-environment.j2` template updated

## 2026-04-09

- Feat #55: `printer status` Slack command — shows current SANDY_PRINTER value, IPP vs CUPS type, TCP connectivity test for IPP URIs, available CUPS queues, and auto-discovered IPP printers; enables full printer diagnosis without SSH (351 tests, 84.90% coverage)
- Feat: IPP auto-discovery fallback in `_lp_print` — when CUPS says "printer does not exist", tries `lpinfo -v` to find IPP URIs on the network and retries with them; logs discovered URI on success so Tom can save it to sandy.toml permanently
- Feat: startup logging now distinguishes IPP vs CUPS printer with a warning when SANDY_PRINTER is a CUPS queue name
- Feat #90: add Sentry error monitoring — sentry-sdk initialized at module level in daemon.py; reads SENTRY_DSN env var; no-op when empty or DEBUG=true (PR #91, part of metaframework#161)

## 2026-04-08
- Fix #55 (part 2): bypass CUPS for IPP URI printers — when SANDY_PRINTER is an `ipp://` URI, Sandy now sends the job directly via HTTP/IPP (RFC 8011) without going through CUPS; fixes `lp: Error - The printer or class does not exist` on Linux homelab where CUPS does not accept raw URIs as queue destinations; also logs config path and resolved printer name at startup for easy diagnosis (342 tests, 85.93% coverage)
- Fix #55: always use `lp -d` for print commands — removes `lpr` (cups-bsd) dependency that's not installed by default on Linux; `lp -d` works for both CUPS queue names and IPP URIs; removes dead `_is_ipp_uri` function; adds regression test `test_print_pdf_ipp_env_uses_lp` (330 tests, 85.5% coverage)

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
