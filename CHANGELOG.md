# Sandy Changelog

## 2026-09-19
- Fix #204: `text` reaching Slack is a mrkdwn field and nothing escaped it, so an exception or upstream API string containing `<@U12345>` arrived as a **real mention**. `sandy/transports/slack.py` now escapes `&`, `<` and `>` in `text`, and in link *labels* — which are built from the same upstream data (a Spotify album name containing `>` silently truncated the link).
- **The ticket left the decision open and the measurement closed it.** It asked whether to escape at the transport ("touches every plugin's output — worth checking which do before touching it") or to declare `text` a mrkdwn field plugins own. Checked: **three plugins deliberately emit mrkdwn in `text`** — `help.py` (`*name*` plus backticked commands), `sports.py` (`*Everton* (FT)`) and `printer_status.py` (`*SANDY_PRINTER:*`). A blanket escape is a visible regression for all three, so the answer is neither option as written: escape the three characters Slack documents an escape for, leave the three it does not, and say so in the contract.
- That split is the line between two failure modes, not a compromise between two options. `<...>` is Slack's control syntax for mentions and links — the only shape here that can *do* something rather than merely look wrong. `*` and `_` are cosmetic, in active deliberate use, and Slack publishes no escape for them at all; the workarounds are a zero-width space or a backtick wrap, both of which corrupt copy-paste.
- **`<...>` is not unused in `text` today, and the first draft of this entry claimed it was.** An AST sweep of every string literal under `sandy/` finds four user-facing producers: `dispatch.py:637` (`` `dispatch shift <kind>` ``), `dispatch.py:78-79` (the `command_groups` rows `help.py` renders), `cast_to_tv.py:117` and `music_discovery.py:235`. All four are *placeholder* syntax, none matches a Slack control sequence (`<@`, `<#`, `<!`, `<http`), so Slack renders them literally today and receives them as entities now. **That is the one user-visible change here and it is unverified against a live workspace** — it depends on Slack decoding `&lt;` inside an inline code span, which its docs imply and which nothing in this repo can prove. `test_dispatch_placeholder_syntax_is_escaped_end_to_end` pins the behaviour so the question is at least visible; if Slack does not decode there, `help` output reads `&lt;kind&gt;` and this needs narrowing.
- Link **URLs** are deliberately left unescaped, reversing a first cut that escaped them. `&` in a URL is a query separator, and escaping it would rewrite every OAuth link Sandy hands out — `music login`'s Spotify URL carries `scope`, `state` and `redirect_uri`. It also buys nothing: `<` and `>` cannot legally appear unescaped in a URI. `|` is not escaped in labels either, because Slack splits on the *first* pipe.
- Escaping happens **before** the 3000-character cap, not after. Capping the raw text first lets escaping push the payload back over Slack's hard section limit and get the whole message rejected. That ordering introduces a second edge — a cut landing inside `&amp;` ships a literal `&am` — so a trailing partial entity is trimmed. The first test written for that was vacuous: `&amp;` is 5 characters and 3000 divides by 5, so an all-ampersand payload can never straddle the boundary. A mutation round caught it — deleting the trim SURVIVED — and the test now uses a deliberately unaligned 2998-character prefix.
- The links section is now capped too (pre-existing gap: `spotify` appends one link per new release, and a section over 3000 characters gets the *whole message* rejected). It is capped by whole lines rather than characters, because a cut inside a `<url|label>` leaves a dangling `<` that swallows the rest of the message. When no line fits at all the block is **omitted** rather than emitted empty — Slack rejects a zero-length text object, so the naive version turned a risk of an over-length rejection into a certainty — and the drop is logged at WARNING, because for `spotify` the links *are* the answer. A line that does not fit is skipped rather than stopped at: the order is upstream's, so `break` made which links survived depend on where the long one happened to land. All three found by the PR reviewers, in code this change itself added.
- `code_text` is **not** escaped, and two tests pin that — including the `_FENCED_RE` auto-promotion path, where the same bytes that would be escaped as `text` must survive verbatim once promoted. `rich_text_preformatted` is literal, so escaping there would display `&amp;` to the reader.
- The decision itself is pinned end-to-end on both halves rather than only in unit tests: `test_sports_bold_survives_the_transport_end_to_end` drives real `sports` output through `format_response` so a future blanket escape goes red on a plugin it would actually break, and the `dispatch` test above does the same for the `<...>` half. Mutation round: 13 mutants, 13 killed, comment-only control survived. (660 tests, 88.03% coverage)
- Not changed: `title`, because a `header` block does not parse mentions or links, and the `via *plugin*` context line, whose only input is the plugin's own module name.
- Fix #207: a present-but-empty `title`, `text` or `image_url` no longer ships a zero-length Block Kit string. Slack requires 1+ characters in every `text` object, `plain_text` header, image `alt_text` and `image_url`, and a zero-length one rejects the **whole message** — so emitting the block is strictly worse than omitting it. This is the rule #204 established on the links section, applied to the remaining producers.
- **The ticket named two sites and there were four.** `title` and `text` are the two it found. The third is `alt_text`: `response.get("title", plugin_name)` cannot fire its default when the key is *present* and empty, so fixing the header alone would have left the message rejected on exactly the path the fix was for — the dict default is the bug, and `or` is the fix. The fourth is `image_url` itself, `if "image_url" in response:`, the identical membership-test pattern one field away in the same block; found by the PR reviewer after the first three were written, and the argument for it is the one #207 used to justify the first two — no plugin emits it today, and that is a property of today's plugins rather than of the contract.
- **The guard reads the escaped body, not the raw input.** `_escaped_mrkdwn` caps and then trims a partial entity, so a non-empty input can still yield an empty field; the length is not knowable before those run. At the real 3000-character cap this is provably unreachable — every escape carries a `;` within four characters, so a whole escaped payload can never match `&[a-z]*\Z` — which is precisely why the first test for it was worthless: it fed `""`, making it a duplicate of the empty-input test with a docstring claiming otherwise. A mutation of the decision it named (`if body:` → `if text:`) **survived** it. The test now lowers `_TEXT_CAP` so the case exists at all, and kills that mutant.
- These guards are only safe because the `via *plugin*` context block is unconditional — Slack rejects `blocks: []` as well — so that precondition is now pinned by a test rather than left as an accident.
- Every drop is logged at WARNING, following the links path rather than inventing a second convention: a dropped block removes user-facing content, and the only other way it surfaces is a user asking where it went. It also makes the deferred copy question answerable with data.
- **Deliberately not decided: the copy.** #207 asks whether an all-empty response should read "nothing to report" instead of a bare `via *plugin*` line; that is Tom's call. Shipping the guards without it is still strictly better than today, where the same response gets Slack's `invalid_blocks` rejection and the user receives *nothing at all* — `reply_fn` has no `except` — so the failure is currently silent and invisible. After this it is confusing but visible, and it names the plugin that produced nothing.
- `format_response` crossed ruff's complexity ceiling once the guards were in, so the header, text and image blocks are now built by three small functions that return a block or `None`. Behaviour is unchanged; the function reads as composition rather than a run of `if`s.
- `alt_text` is capped at 2000 and the header at 150 — one title feeds both and neither limit covers the other. Pre-existing, on a line this change already touched.
- Mutation round: 7 mutants, 7 killed, comment-only control survived. (687 tests, 88% coverage)

## 2026-09-18
- Fix #199: #187's twin, one branch over. A plugin that *matched* and then raised got two answers — `spotify plugin failed: <msg>` on stderr from `cli.py`, `I am terribly sorry, spotify just does not want to behave!` from `daemon.py`. Both boundaries now call one definition, `sandy.pipeline.format_plugin_error`. The **daemon's** wording is the one kept this time, the reverse of #187: `CLAUDE.md` line 81 cites it as the house example of a friendly failure against `ERROR: plugin raised RuntimeError` as the anti-example, and the CLI's line was much the nearer of the two to the anti-example.
- **Three things differed, not one.** Wording, above. The **cap**: the daemon truncated detail at 100 characters and the CLI emitted the whole exception, so `PLUGIN_ERROR_DETAIL_LIMIT` is now shared — an unbounded stack string is no more welcome in a terminal than on a Slack channel. And the **markup**: the daemon wrapped detail in backticks, which is Slack mrkdwn baked into a string the CLI also prints. The backticks are gone; `sandy.transports.slack.format_response` owns markup and its own docstring already prefers a `code_text` block over fences in `text` (#122).
- The **stream** deliberately did not change. The CLI still writes failures to stderr and the daemon still replies through the channel — that difference is the surfaces being different, not the message drifting.
- Truncation now ends in `...`, and the marker counts against the cap so the detail is never longer than 100 characters. A bare slice tells the reader a lie: a cut exception is indistinguishable from a whole one, which matters most on the long messages where the tail is the informative part.
- The constant and the formatter live in `pipeline.py`, beside `NO_MATCH_MESSAGE` and beside `run_pipeline`'s `except` clause — which is what catches the exception and appends the `(plugin_name, error_message)` tuple. #199 suggested a new `sandy/messages.py` on the grounds that two shared strings is where one earns its keep; declined, because the argument that put the first one here (defined beside the condition it describes, in a module both boundaries already import, and **not** a module named for voice — sandy#184) applies unchanged to the second. That is a one-line call to reverse if Tom prefers the split.
- `test_callback_plugin_error_no_message_omits_backticks` had gone **vacuous** rather than failing: with backticks removed from every branch its `"`" not in text` assertion was true by construction and could no longer catch anything. Renamed to `..._omits_detail` and re-pointed at what the no-message branch actually decides — that the headline is emitted exactly, with nothing appended.
- New `tests/test_plugin_error_parity.py` asserts the two surfaces equal **each other**, parametrised over an ordinary message, an empty one and one over the cap — the edges are where they forked, and a test that only ever raises a short exception cannot see it. Parity alone is also satisfiable by *removing* the daemon's cap, so a separate test pins the bound on the surface that never had one.
- **Slack error detail stays in `text` rather than moving to a `code_text` block**, which is the half of "leave the backticks to the transport" that #199 asked for and this does not do. Two measurements against it: `sandy.plugins.dispatch._http_error_message` already decided the same question the other way in its docstring — "errors go into `text` (not `code_text`) so Slack renders them inline" — and `format_response` emits `code_text` *before* `text` by design (`test_format_response_code_text_alongside_text` pins it), so the raw exception would render above the sentence apologising for it. The residue is real and is now named rather than assumed: exception text reaching Slack is interpreted as mrkdwn, so `*x*` in a message renders bold where the backticks used to suppress it. That is a repo-wide property of every `text` payload rather than something this change introduced, and it is filed separately.
- New `test_the_daemons_error_payload_renders_as_one_inline_slack_block` — the daemon's `reply_fn("error", ...)` payload had never met `format_response` in any test, so the rendering on the surface this fix is *about* was unguarded in both directions.
- **Two parity tests were overclaiming, in this file and in #187's.** `test_both_surfaces_emit_the_shared_*` derives its expected value by calling the same definition both boundaries call, so it only re-proves output equality — measured: replacing `daemon.py`'s call with an inline copy producing byte-identical text left the whole suite green. Both files gain a test that patches the name *as each module imported it* and asserts a sentinel comes back, which fails the instant a boundary stops routing through the shared name. The docstrings now claim only what each test proves.

## 2026-09-17
- Fix #187: the CLI and the Slack daemon gave two different answers to the same no-match condition — `I don't know how to do that yet.` from `cli.py`, `Sorry, I'm not sure how to do that.` from `daemon.py`. Same event, different voice, decided by where you typed. Both now read one definition, `sandy.pipeline.NO_MATCH_MESSAGE`. The CLI's wording is the one kept: `README.md` documents it and `CLAUDE.md` cites it as the house example of a friendly failure, so the daemon is what moved.
- The constant lives in `pipeline.py`, beside the matching it describes and **not** in a module named for voice. That is the #184 lesson applied rather than re-learned: a `sandy/voice.py` was rejected on 2026-08-24, and a personality module is an invitation to add unprompted personality. Both boundaries already imported from `pipeline`, so nothing new was coupled.
- The daemon half had no working coverage. `test_callback_no_match_sends_fallback` re-implemented `_handle_callback`'s dispatch loop — including the literal — instead of calling it, so it asserted against its own copy of the production code and would have stayed green through any edit to `daemon.py`. Its own inline comment already claimed it called the callback directly. It now does; verified by mutation.
- The new `tests/test_no_match_parity.py` asserts the two surfaces equal **each other**, so a reword that touches only one of them fails whatever words are picked. It pins the shared constant as well, since parity alone is also satisfied by two literals that happen to agree; the wording itself stays guarded by the pre-existing literal in `tests/test_cli.py`.
- Out of scope, deliberately: echoing the unmatched text back to the user. That is a copy change and Tom's to pick (#187), and Slack control syntax (`<!channel>`, `<@U123>`) would have to be defused first or Sandy could ping a channel to announce she did not understand.

## 2026-09-15
- Fix #190 (Sentry SANDY-4): a Cloudflare `530` on `dispatch pm` no longer opens a Sentry incident, and no longer says "dispatchd returned 530" — a sentence that blames dispatchd for a response it never sent. dispatchd serves on `127.0.0.1:8787` only — `DEFAULT_BIND_HOST` with no override, and behind that an app-layer `DEFAULT_ALLOW_IPS` of `127.0.0.1/32`/`::1/128`, so even a mis-set bind host would not expose it — so every Sandy call arrives through the tunnel and `520`–`527`/`530` are statuses it is *structurally incapable* of emitting; they are the edge's verdict about an origin that did not answer. `_is_unreachable()` now treats them as the same condition as `URLError` and `TimeoutError` — "the Mac is asleep or off-network" — which is an ordinary state here rather than a Sandy defect, so every future occurrence would have been a false positive by construction.
- **The ticket's premise was wrong and that is worth recording.** It reported an *unhandled* `HTTPError`. Sentry's own tag on the event is `handled: yes`: the read path already caught it, Tom already got a friendly Slack message, and `capture()` filed the event deliberately. The ask "add error handling" was already satisfied; the only live question was the category.
- **This walks back a slice of #129 (2026-06-30) on purpose, and the boundary matters.** That entry records Sentry staying silent for two months because these plugins swallow their own failures — so unreachability is *downgraded*, not deleted: `_report()` logs it, and since `observability` installs `LoggingIntegration(event_level=None)` the record becomes a breadcrumb that is there on any later real incident without opening one now. What stays an incident: a `500` from dispatchd itself, and — the load-bearing one — cloudflared's own `502`, which in this topology *typically* means connector up and `127.0.0.1:8787` refusing, i.e. Mac awake and daemon dead. That is reasoned from how cloudflared ingress behaves, not observed on this tunnel, and an origin-refused can surface as `521`/`523` instead — but every reading leaves `502` an incident, so the conclusion does not rest on it. Exempting "any 5xx" would have silenced exactly that.
- A `4xx` on a *read* also still reports. The write path exempts `4xx` because there it is the endpoint rejecting user input (bad URL, missing cap, 409 busy); a GET carries no user input, so its only `4xx` are `401`/`403`/`404` — config defects, and the Browser-Integrity `403` of 2026-07-14 was a real bug that needed reporting. The asymmetry is deliberate.
- **No retry was added, deliberately.** The cause is a sleeping Mac, not a blip a bounded retry inside the plugin's 5-second HTTP timeout could ride out; it would only delay the reply.
- Tunnel or origin, per the ticket's own ask: neither process died. dispatchd last started 2026-08-28 23:59 and cloudflared has run since 28 Aug, both continuously across 2026-09-01 — which rules out a crash-restart, not a hang. A momentary edge-to-origin loss or a sleeping Mac is what remains. Whether the Mac was asleep is no longer answerable; `pmset -g log` only reaches back to 2026-09-08.
- Every capture decision in the plugin now routes through one `_report()`. The first cut of this fix inlined the rule at three call sites and review found the third untested — deleting that guard left all 123 tests in the plugin's own file green. (641 tests, 88% coverage)

## 2026-08-24
- Docs #183: `CLAUDE.md` gains an **Inspiration** section recording where the name comes from — Eugene Wei's [I Want Sandy](https://www.eugenewei.com/blog/2014/1/7/i-want-sandy) — and turns it into rules an agent can follow rather than background colour: prefer the human string to the merely-correct one, freeform text over subcommands, and a switch on every flourish because Wei asked for one. `README.md` points at it.
- **The implementation half of #183 was built and then reverted before merge, on Tom's call** — a `sandy/voice.py` that opened small-hours replies with an aside about the hour, plus its CLI/daemon/Slack wiring and a `[sandy] flourishes` switch. *"I love the thought here but that feels like too much of a flourish."* The origin documentation is the part he wanted; the personality layer was an agent inferring intent from "lean into that". `CLAUDE.md`'s Inspiration section now says so explicitly, so the next reader does not re-derive it. See PR #184.
- Fix: a plugin's `progress()` message could be delivered to nobody. It is queued from the executor thread via `call_soon_threadsafe`, and the end-of-pipeline sentinel was posted without first letting that callback run — so the drain task could see `None` first and exit. Pre-existing; no test covered the path until #183 added one, which then failed on Linux/CPython 3.13.15 while passing on macOS/3.13.7. The regression test that ships with the fix drives the interleaving directly rather than relying on the race, because the end-to-end version is green on macOS with the fix removed; the end-to-end test is kept alongside it as a canary over the real executor path, labelled as such.
- Fix: that `sleep(0)` is a real suspension point, so a SIGTERM landing on it would have skipped the sentinel and stranded the progress drain task on `get()` forever. The teardown now cancels the drain task in its own `finally` — a no-op when it has already finished.

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
