"""Sandy plugin: Dispatch commands.

A window into the Dispatch automation system, plus two write commands — one
that hands an agent a piece of work, one that re-fires a scheduled shift.

Commands:
  "dispatch status"      — current state from memory.md
  "dispatch check"       — dispatchd health and in-flight run status
  "dispatch pm"          — contents of PM Inbox.md
  "dispatch work <URL>"  — hand a GitHub issue/PR URL to an ad-hoc agent run
  "dispatch shift <kind>" — trigger a Mac-side ``dispatch <kind>`` run

There is one backend: dispatchd's ``/v1/*`` surface (metaframework #326 for
the reads, #382 for ``POST /v1/dispatch/shift``, #435 for
``POST /v1/dispatch/work``), reached over HTTP with HMAC-SHA256 request
signing. The plugin is configured by three env vars —
``DISPATCHD_BASE_URL``, ``DISPATCHD_KEY_ID``, and ``DISPATCHD_SECRET``. When
any of them is unset, every command returns a friendly "not configured"
message; there is no local-file fallback (Mac dev runs dispatchd from the
metaframework repo, same as production).

``dispatch work`` and ``dispatch shift`` are the commands here that change
anything. They are gated the same way the read commands are —
``[permissions]`` in ``sandy.toml`` leaves the ``dispatch`` plugin at
``default_access = "private"``, so only the owner reaches them — and again
server-side by a capability on the dispatchd key. The two caps are
deliberately separate: ``work`` points an agent at an arbitrary repo,
``shift`` only re-fires a preset, and neither implies the other.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from typing import Callable, NamedTuple, NotRequired, TypedDict

from sandy.matcher import normalize
from sandy.observability import capture

name = "dispatch"
commands = [
    "dispatch status",
    "dispatch check",
    "dispatch pm",
    "dispatch work",
    "dispatch shift",
]

# `dispatch work` and `dispatch shift` are useless without an argument, so each
# gets its own help row naming the argument instead of sitting as a bare leaf
# next to the three read commands (the `command_groups` convention from
# itguy#131).
command_groups = {
    "dispatch work": ["dispatch work <github issue or PR URL>"],
    "dispatch shift": ["dispatch shift <night|day|wrapup|pmreview|sanity|selffix>"],
}

_HTTP_TIMEOUT_SECONDS = 5

_NOT_CONFIGURED_TEXT = (
    "Sandy is not configured to reach dispatchd.\n"
    "Set DISPATCHD_BASE_URL, DISPATCHD_KEY_ID, and DISPATCHD_SECRET "
    "(see metaframework docs/dispatchd.md)."
)

# Shared by both spawn commands. dispatchd's in-flight registry only records
# runs its *own* endpoints started, so a launchd-started shift leaves no row and
# a 202 during one is genuine — the child then loses the `LockManager` race and
# exits (meta#438). Saying "spawned" and pointing at `dispatch check` is the
# honest reading of a 202; saying "running" is not.
_SPAWN_CAVEAT = (
    "Heads up: 202 means it was spawned, not that it's running — a "
    "scheduled shift can still be holding the lock. Run `dispatch check` "
    "in a minute to confirm it took."
)


# ---------------------------------------------------------------------------
# Wire shapes (docs/dispatchd.md) and the plugin response contract
# ---------------------------------------------------------------------------


class InFlightRow(TypedDict, total=False):
    """One in-flight run from /v1/health — dispatchd's ``Run.as_dict()``
    (metaframework ``dispatchd/registry.py``). The run kind lives under
    ``shift``."""

    run_id: str
    shift: str
    status: str
    pid: int
    started_at: str
    ended_at: str | None
    exit_code: int | None


class WorkTarget(TypedDict, total=False):
    """The GitHub target dispatchd re-derived from the URL we posted."""

    owner: str
    repo: str
    kind: str  # "issue" | "pull"
    number: int


class EnvelopeData(TypedDict, total=False):
    """Union of the ``data`` payloads across the endpoints we call:
    ``text`` for /v1/dispatch/status and /v1/dispatch/pm-inbox,
    ``status`` + ``in_flight`` for /v1/health, and the run handshake
    (``run_id`` + ``target``) for /v1/dispatch/work."""

    text: str
    status: str
    in_flight: InFlightRow | None
    run_id: str
    url: str
    target: WorkTarget
    started_at: str


class Envelope(TypedDict, total=False):
    data: EnvelopeData
    as_of: str


class PluginResponse(TypedDict):
    text: str
    title: NotRequired[str]


# ---------------------------------------------------------------------------
# HTTP backend (dispatchd HMAC bearer, docs/dispatchd.md)
# ---------------------------------------------------------------------------


def _http_config() -> tuple[str, str, str] | None:
    """Return (base_url, key_id, secret) if fully configured, else None.

    All three env vars must be set — a partial config is treated as
    unconfigured rather than half-authenticating a request that will 401.
    Trailing slash on ``DISPATCHD_BASE_URL`` is normalized so callers can
    set either shape.
    """
    base_url = os.environ.get("DISPATCHD_BASE_URL", "").strip().rstrip("/")
    key_id = os.environ.get("DISPATCHD_KEY_ID", "").strip()
    secret = os.environ.get("DISPATCHD_SECRET", "").strip()
    if not (base_url and key_id and secret):
        return None
    return base_url, key_id, secret


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects: urllib forwards the Authorization, X-Nonce,
    and X-Timestamp headers to the redirect target — even cross-host — which
    would hand a replayable signature to whatever the server 302s to. A 3xx
    from dispatchd is an error, not a hop."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _call_dispatchd(path: str, *, method: str = "GET", payload: dict | None = None) -> Envelope:
    """Call a dispatchd endpoint with HMAC-SHA256, return the parsed envelope.

    Signature and header shape are defined in ``docs/dispatchd.md``:
    ``HMAC-SHA256(secret, method \\n path \\n sha256(body) \\n nonce \\n ts)``.
    All 4xx/5xx responses raise ``urllib.error.HTTPError``, which the
    caller translates into a Sandy error message rather than propagate.

    ``payload`` is JSON-encoded once and the *same bytes* are both hashed
    into the canonical string and sent as the body — re-serializing for the
    send would risk a signature over different bytes than the server hashes,
    which presents as an unexplainable 401.
    """
    config = _http_config()
    if config is None:
        raise RuntimeError("dispatchd HTTP backend not configured")
    base_url, key_id, secret = config

    nonce = secrets.token_urlsafe(16)
    ts = str(int(time.time()))
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    body_sha = hashlib.sha256(body).hexdigest()
    canonical = f"{method}\n{path}\n{body_sha}\n{nonce}\n{ts}".encode()
    sig = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()

    headers = {
        "Authorization": f"HMAC {key_id}:{sig}",
        "X-Nonce": nonce,
        "X-Timestamp": ts,
        # Cloudflare's Browser Integrity Check (error 1010) bans the
        # default Python-urllib UA before the request reaches dispatchd.
        # Naming follows the dispatch-family convention set by
        # dispatchd-mcp/1.0 (metaframework oauth.py, same CF issue).
        "User-Agent": "dispatch-sandy/1.0",
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        base_url + path,
        data=body or None,
        headers=headers,
        method=method,
    )
    with _OPENER.open(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_error_message(exc: Exception, kind: str) -> str:
    """Format a Sandy-friendly error for an HTTP call failure.

    Errors go into ``text`` (not ``code_text``) so Slack renders them
    inline. Keep the message short — full traceback lands in the daemon
    log and Sentry, not in Slack.
    """
    if isinstance(exc, urllib.error.HTTPError):
        return f"dispatchd returned {exc.code} for {kind}."
    if isinstance(exc, urllib.error.URLError):
        return f"dispatchd unreachable ({exc.reason}) for {kind}."
    # A timeout after connect raises bare TimeoutError, not URLError.
    if isinstance(exc, TimeoutError):
        return f"dispatchd unreachable (timed out) for {kind}."
    return f"dispatchd {kind} failed: {exc}"


# ---------------------------------------------------------------------------
# Per-endpoint formatters
# ---------------------------------------------------------------------------

# Strip YAML-style metadata blocks from the top
_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)


def _extract_current_status(raw: str) -> str:
    """Pull the ``## Current Status`` section, or first 20 lines as fallback."""
    match = re.search(r"## Current Status\n(.*?)(?=\n## |\Z)", raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    lines = raw.splitlines()
    if len(lines) <= 20:
        return "\n".join(lines)
    return "\n".join(lines[:20]) + "\n… (first 20 lines of memory.md)"


def _format_in_flight(row: InFlightRow | None) -> str:
    if not row:
        return "In-flight: none."
    kind = row.get("shift", "?")
    pid = row.get("pid", "?")
    started = row.get("started_at", "?")
    return f"In-flight: {kind} (pid {pid}, started {started})."


def _format_status(envelope: Envelope) -> str:
    text = (envelope.get("data") or {}).get("text", "")
    if not text:
        return "memory.md is empty."
    return _extract_current_status(text)


def _format_health(envelope: Envelope) -> str:
    data = envelope.get("data") or {}
    lines = [
        f"Health: {data.get('status', '?')}",
        _format_in_flight(data.get("in_flight")),
    ]
    as_of = envelope.get("as_of")
    if as_of:
        lines.append(f"As of: {as_of}")
    return "\n".join(lines)


def _format_pm(envelope: Envelope) -> str:
    text = (envelope.get("data") or {}).get("text", "")
    if not text.strip():
        return "PM Inbox is empty."
    return _FRONTMATTER_RE.sub("", text.strip()).strip()


# ---------------------------------------------------------------------------
# "dispatch work <URL>" — POST /v1/dispatch/work (sandy #137 Part C)
# ---------------------------------------------------------------------------

_WORK_TITLE = "Dispatch Work"

# Anchored so the work matcher can never swallow "dispatch status"/"check"/"pm".
# DOTALL because Slack can deliver a pasted link with a trailing newline.
_WORK_COMMAND_RE = re.compile(r"^dispatch\s+work\b\s*(?P<rest>.*)$", re.IGNORECASE | re.DOTALL)

# Slack renders a bare URL as <url> and a labelled one as <url|display text>.
# Both reach the plugin verbatim, so unwrap before parsing. The label is
# free text and routinely contains spaces (GitHub's unfurl uses the issue
# title), so this is matched against the whole remainder of the message —
# splitting on whitespace first would truncate the link at the label's first
# space and reject a perfectly good paste.
_SLACK_LINK_RE = re.compile(r"^<(?P<url>[^|>\s]+)(?:\|[^>]*)?>")

# The accepted shapes are dispatchd's, restated client-side so a bad paste is
# answered instantly instead of costing a signed round trip (docs/dispatchd.md).
_GITHUB_TARGET_RE = re.compile(
    r"^https?://(?:www\.)?github\.com"
    r"/(?P<owner>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"/(?P<repo>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"/(?P<kind>issues|pull)"
    r"/(?P<number>\d+)/?$",
    re.IGNORECASE,
)

_ACCEPTED_SHAPES = "https://github.com/OWNER/REPO/issues/N or https://github.com/OWNER/REPO/pull/N"

# Keyed on dispatchd's machine `error` code rather than the HTTP status, because
# 403 covers three genuinely different fixes (grant a cap / allow an owner /
# untangle a symlink) and the caller needs to know which one is theirs.
_WORK_ERROR_TEXT: dict[str, str] = {
    "bad_request": (
        f"That isn't a URL I can work. Give me {_ACCEPTED_SHAPES} — "
        "an issue or pull-request link, not a repo, discussion, or file."
    ),
    "forbidden": (
        "This Sandy key doesn't carry the `work` capability, so it can't hand "
        'out work. Add "work" to its caps in dispatchd\'s config and reload the '
        "launchd unit."
    ),
    "forbidden_owner": (
        "dispatchd refused that repo's owner — it isn't in `allow_repo_owners` "
        "(DISPATCH_ALLOW_REPO_OWNERS)."
    ),
    "forbidden_path": (
        "The checkout that URL resolves to sits outside dispatchd's work "
        "directory, so it refused to touch it. Likely a symlink in the way."
    ),
    "repo_not_found": (
        "There's no local checkout for that repo on the Mac, and dispatchd "
        "won't clone one for you. Clone it under the work directory, then "
        "re-send."
    ),
    "conflict": (
        "dispatchd already has a run in flight, so it didn't start another one. "
        "Try `dispatch check` to see what it's busy with, then re-send once "
        "that clears."
    ),
}


def _parse_work_command(text: str) -> str | None:
    """Return the canonical GitHub URL from a ``dispatch work <URL>`` message.

    Returns ``None`` for anything this command can't act on — a different
    dispatch command, a missing URL, or a URL that isn't an issue/PR link.
    Callers that need to tell "not my command" apart from "bad URL" should
    match ``_WORK_COMMAND_RE`` first.

    Canonical means: scheme forced to https, ``www.`` dropped, owner/repo/kind
    lowercased, and any ``#issuecomment-N`` fragment or query string removed.
    Posting the canonical form rather than the raw paste means the target
    dispatchd's checks ran against is exactly the one the agent re-parses.
    """
    match = _WORK_COMMAND_RE.match(text.strip())
    if match is None:
        return None
    rest = match.group("rest").strip()
    if not rest:
        return None

    # Unwrap an angle-bracket link against the full remainder first, then fall
    # back to the first whitespace-delimited token for a bare paste. Order
    # matters: a labelled Slack link may carry spaces inside the brackets.
    slack_link = _SLACK_LINK_RE.match(rest)
    candidate = slack_link.group("url") if slack_link else rest.split()[0]
    # A comment permalink is the most natural thing to paste out of a thread.
    candidate = candidate.split("#", 1)[0].split("?", 1)[0]

    target = _GITHUB_TARGET_RE.match(candidate)
    if target is None:
        return None
    return (
        f"https://github.com/{target['owner'].lower()}/{target['repo'].lower()}"
        f"/{target['kind'].lower()}/{target['number']}"
    )


def _describe_target(target: WorkTarget | None) -> str:
    """Human label for the target dispatchd echoed back, e.g. 'tclancy/sandy issue 137'."""
    if not target:
        return "the target"
    owner = target.get("owner", "?")
    repo = target.get("repo", "?")
    kind = "PR" if target.get("kind") == "pull" else "issue"
    return f"{owner}/{repo} {kind} {target.get('number', '?')}"


def _format_work(envelope: Envelope) -> str:
    """Render the 202 handshake.

    Deliberately says *spawned*, never *running* (meta#438). dispatchd's
    in-flight registry only knows about runs its own endpoints started, so a
    202 during a launchd-started shift is real — and the child then loses the
    `LockManager` race and exits. Pointing at `dispatch check` gives the honest
    confirmation the 202 can't.
    """
    data = envelope.get("data") or {}
    lines = [f"Spawned an agent on {_describe_target(data.get('target'))}."]
    run_id = data.get("run_id")
    if run_id:
        lines.append(f"Run: {run_id}")
    lines.append(_SPAWN_CAVEAT)
    return "\n".join(lines)


def _read_error_payload(exc: urllib.error.HTTPError) -> tuple[str, str] | None:
    """Return (error_code, message) from a dispatchd error body, or None.

    None means the body wasn't dispatchd's JSON envelope at all — a proxy or
    Cloudflare error page in front of the daemon, which must degrade to the
    generic transport message rather than crash on a JSON decode.
    """
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return str(payload.get("error", "")), str(payload.get("message", ""))


def _write_http_error_message(
    exc: urllib.error.HTTPError, kind: str, error_text: dict[str, str]
) -> str:
    """Translate a dispatchd error body into Slack copy for a write command.

    Keyed on the machine ``error`` code rather than the HTTP status because one
    status can cover several genuinely different fixes. A code with no entry in
    ``error_text`` falls through to dispatchd's own ``message``, which is the
    right default when the server's phrasing is more current than anything the
    client could hardcode (see ``_SHIFT_ERROR_TEXT``).
    """
    parsed = _read_error_payload(exc)
    if parsed is None:
        return _http_error_message(exc, kind)
    code, message = parsed
    known = error_text.get(code)
    if known:
        return known
    if message:
        return f"dispatchd returned {exc.code} for {kind}: {message}"
    return _http_error_message(exc, kind)


class _WriteCommand(NamedTuple):
    """A POST endpoint plus the copy used to render its outcomes."""

    path: str
    title: str
    kind: str  # short label for error messages and Sentry's `stage` tag
    error_text: dict[str, str]
    format: Callable[[Envelope], str]


def _post_command(command: _WriteCommand, payload: dict) -> PluginResponse:
    """POST to a write endpoint and render the result.

    Shared by ``dispatch work`` and ``dispatch shift`` so the capture policy
    below is decided once. Both commands reach dispatchd the same way and
    differ only in payload, copy, and the error codes they can provoke.
    """
    try:
        envelope = _call_dispatchd(command.path, method="POST", payload=payload)
        return {"title": command.title, "text": command.format(envelope)}
    except urllib.error.HTTPError as exc:
        # 4xx here is the endpoint working as designed (bad input, missing cap,
        # busy) — user-facing control flow, not an incident. Only 5xx is.
        if exc.code >= 500:
            capture(exc, plugin="dispatch", stage=command.kind)
        return {
            "title": command.title,
            "text": _write_http_error_message(exc, command.kind, command.error_text),
        }
    except Exception as exc:
        capture(exc, plugin="dispatch", stage=command.kind)
        return {"title": command.title, "text": _http_error_message(exc, command.kind)}


_WORK_COMMAND = _WriteCommand(
    path="/v1/dispatch/work",
    title=_WORK_TITLE,
    kind="work",
    error_text=_WORK_ERROR_TEXT,
    format=_format_work,
)


def _run_work(raw: str) -> PluginResponse:
    if _http_config() is None:
        # Expected on a fresh install — control flow, not a Sentry event.
        return {"title": _WORK_TITLE, "text": _NOT_CONFIGURED_TEXT}

    url = _parse_work_command(raw)
    if url is None:
        return {"title": _WORK_TITLE, "text": _WORK_ERROR_TEXT["bad_request"]}

    return _post_command(_WORK_COMMAND, {"url": url})


# ---------------------------------------------------------------------------
# "dispatch shift <kind>" — POST /v1/dispatch/shift (sandy #137 Part A)
# ---------------------------------------------------------------------------

_SHIFT_TITLE = "Dispatch Shift"

# Anchored so this matcher can never swallow "dispatch status"/"check"/"pm".
_SHIFT_COMMAND_RE = re.compile(r"^dispatch\s+shift\b\s*(?P<rest>.*)$", re.IGNORECASE | re.DOTALL)

# Listed for humans only — dispatchd owns the authoritative vocabulary
# (`SHIFT_KINDS` in metaframework `dispatchd/actions.py`). Deliberately NOT
# used to validate: a client-side allowlist drifts into refusing a kind the
# server has since added, and a false refusal is a worse failure than one
# wasted round trip. dispatchd's 400 already names the valid set, so an
# unknown kind is answered by `_write_http_error_message` echoing it. That
# makes this tuple purely documentation — if it goes stale the help text is
# mildly wrong, and nothing breaks.
_SHIFT_KINDS = ("night", "day", "wrapup", "pmreview", "sanity", "selffix")

_SHIFT_HELP = (
    "`dispatch shift <kind>` runs a Dispatch shift on the Mac.\n"
    f"Kinds: {', '.join(_SHIFT_KINDS)}.\n"
    "Fire-and-forget — I'll reply with a run id; use `dispatch check` for status."
)

_SHIFT_ERROR_TEXT: dict[str, str] = {
    "forbidden": (
        "This Sandy key doesn't carry the `shift` capability, so it can't start "
        'a shift. Add "shift" to its caps in dispatchd\'s config and reload the '
        "launchd unit."
    ),
    "conflict": (
        "dispatchd already has a run in flight, so it didn't start another one. "
        "Try `dispatch check` to see what it's busy with, then re-send once "
        "that clears."
    ),
    # `bad_request` is intentionally absent — see _SHIFT_KINDS.
}


class _ShiftParse(NamedTuple):
    """Outcome of reading a ``dispatch shift`` message.

    Exactly one field is set: ``kind`` when there is something to POST,
    ``error`` when the message can't be acted on and the user needs telling.
    """

    kind: str | None = None
    error: str | None = None


def _is_shift_command(text: str) -> bool:
    """True when this message is addressed to ``dispatch shift``."""
    return _SHIFT_COMMAND_RE.match(normalize(text)) is not None


def _parse_shift_command(text: str) -> _ShiftParse:
    """Read the shift kind out of a ``dispatch shift <kind>`` message.

    The whole message is run through sandy's own
    :func:`~sandy.matcher.normalize` before matching, because ``handle``
    receives the *raw* Slack text while routing happened on the normalized
    form — so without this the plugin can be handed a message the framework
    matched and then fail to recognise it. Normalizing lowercases, drops
    punctuation and strips polite framing, which is what lets "Dispatch Shift
    Night", "dispatch shift day." and "please dispatch shift night" all
    resolve. Every token this command takes is a bare lowercase word, so
    nothing is lost to normalization — unlike ``dispatch work``, whose URL
    argument must be read from the raw text.

    A second word is refused rather than dropped. It would be read as a
    ``slot``, and no slot value is safe to send today (see ``_run_shift``);
    silently ignoring an argument the user typed is the bug the `dispatch`
    wrapper itself had to fix in metaframework #284.
    """
    match = _SHIFT_COMMAND_RE.match(normalize(text))
    if match is None:
        return _ShiftParse(error=_SHIFT_HELP)

    words = match.group("rest").split()
    if not words:
        return _ShiftParse(error=_SHIFT_HELP)
    if len(words) > 1:
        extra = " ".join(words[1:])
        return _ShiftParse(
            error=(
                f"I can only take a shift kind, but got {extra!r} after "
                f"{words[0]!r}. Slots aren't wired up yet — send just "
                f"`dispatch shift {words[0]}`."
            )
        )
    return _ShiftParse(kind=words[0])


def _format_shift(envelope: Envelope) -> str:
    """Render the 202 handshake. Says *spawned*, never *running* (meta#438)."""
    data = envelope.get("data") or {}
    kind = data.get("kind")
    lines = [f"Spawned the {kind} shift." if kind else "Spawned the shift."]
    run_id = data.get("run_id")
    if run_id:
        lines.append(f"Run: {run_id}")
    lines.append(_SPAWN_CAVEAT)
    return "\n".join(lines)


_SHIFT_COMMAND = _WriteCommand(
    path="/v1/dispatch/shift",
    title=_SHIFT_TITLE,
    kind="shift",
    error_text=_SHIFT_ERROR_TEXT,
    format=_format_shift,
)


def _run_shift(raw: str) -> PluginResponse:
    """Trigger a shift.

    ``slot`` is always ``None``, and that is load-bearing rather than a
    simplification. dispatchd appends a non-null slot to the child argv
    (``spawn_shift``), but `dispatch`'s top-level parser accepts exactly one
    positional — so ``dispatch dayshift 9am`` exits 2 immediately. By then the
    endpoint has returned 202 with a run_id and written a "running" registry
    row, so the shift looks spawned and never ran. Until that is fixed
    server-side there is no slot value this client can safely send.
    """
    if _http_config() is None:
        # Expected on a fresh install — control flow, not a Sentry event.
        return {"title": _SHIFT_TITLE, "text": _NOT_CONFIGURED_TEXT}

    parsed = _parse_shift_command(raw)
    if parsed.kind is None:
        return {"title": _SHIFT_TITLE, "text": parsed.error or _SHIFT_HELP}

    return _post_command(_SHIFT_COMMAND, {"kind": parsed.kind, "slot": None})


# ---------------------------------------------------------------------------
# Command registry + dispatcher
# ---------------------------------------------------------------------------


class _Command(NamedTuple):
    path: str
    title: str
    kind: str  # short label for error messages and Sentry's `stage` tag
    format: Callable[[Envelope], str]


_COMMANDS: dict[str, _Command] = {
    "dispatch status": _Command("/v1/dispatch/status", "Dispatch Status", "status", _format_status),
    "dispatch check": _Command("/v1/health", "Dispatch Activity", "health", _format_health),
    "dispatch pm": _Command("/v1/dispatch/pm-inbox", "PM Inbox", "pm-inbox", _format_pm),
}


def _run_command(command: _Command) -> PluginResponse:
    if _http_config() is None:
        # Expected on a fresh install — control flow, not a Sentry event.
        return {"title": command.title, "text": _NOT_CONFIGURED_TEXT}
    try:
        # format stays inside the try: a 200 whose JSON isn't the expected
        # envelope shape (null, list, string) must get the same friendly
        # message + tagged capture as a transport failure.
        envelope = _call_dispatchd(command.path)
        return {"title": command.title, "text": command.format(envelope)}
    except Exception as exc:
        capture(exc, plugin="dispatch", stage=command.kind)
        return {"title": command.title, "text": _http_error_message(exc, command.kind)}


def handle(text: str, actor: str) -> PluginResponse:
    raw = text.strip()
    # Matched on the command shape, not on a successful URL parse, so a
    # malformed link gets "that isn't a URL I can work" rather than the
    # generic unknown-command reply.
    if _WORK_COMMAND_RE.match(raw):
        return _run_work(raw)
    # Same reasoning as work: matched on the command shape, not on a successful
    # parse, so a missing or malformed kind gets the help text rather than the
    # generic unknown-command reply.
    if _is_shift_command(raw):
        return _run_shift(raw)
    command = _COMMANDS.get(raw.lower())
    if command is None:
        return {"text": f"Unknown dispatch command: {text!r}"}
    return _run_command(command)
