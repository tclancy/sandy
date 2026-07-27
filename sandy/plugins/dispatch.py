"""Sandy plugin: Dispatch commands.

A window into the Dispatch automation system, plus one write command that
hands an agent a piece of work.

Commands:
  "dispatch status"     — current state from memory.md
  "dispatch check"      — dispatchd health and in-flight run status
  "dispatch pm"         — contents of PM Inbox.md
  "dispatch work <URL>" — hand a GitHub issue/PR URL to an ad-hoc agent run

There is one backend: dispatchd's ``/v1/*`` surface (metaframework #326 for
the reads, #435 for ``POST /v1/dispatch/work``), reached over HTTP with
HMAC-SHA256 request signing. The plugin is configured by three env vars —
``DISPATCHD_BASE_URL``, ``DISPATCHD_KEY_ID``, and ``DISPATCHD_SECRET``. When
any of them is unset, every command returns a friendly "not configured"
message; there is no local-file fallback (Mac dev runs dispatchd from the
metaframework repo, same as production).

``dispatch work`` is the only command here that changes anything. It is
gated the same way the read commands are — ``[permissions]`` in
``sandy.toml`` leaves the ``dispatch`` plugin at ``default_access =
"private"``, so only the owner reaches it — and again server-side by the
``work`` capability on the dispatchd key, which is deliberately *not*
implied by ``shift``.
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

from sandy.observability import capture

name = "dispatch"
commands = [
    "dispatch status",
    "dispatch check",
    "dispatch pm",
    "dispatch work",
]

# `dispatch work` is useless without an argument, so hoist it onto its own help
# row that names the argument instead of listing it as a bare leaf next to the
# three read commands (the `command_groups` convention from itguy#131).
command_groups = {
    "dispatch work": ["dispatch work <github issue or PR URL>"],
}

_HTTP_TIMEOUT_SECONDS = 5

_NOT_CONFIGURED_TEXT = (
    "Sandy is not configured to reach dispatchd.\n"
    "Set DISPATCHD_BASE_URL, DISPATCHD_KEY_ID, and DISPATCHD_SECRET "
    "(see metaframework docs/dispatchd.md)."
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
    lines.append(
        "Heads up: 202 means it was spawned, not that it's running — a "
        "scheduled shift can still be holding the lock. Run `dispatch check` "
        "in a minute to confirm it took."
    )
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


def _work_http_error_message(exc: urllib.error.HTTPError) -> str:
    parsed = _read_error_payload(exc)
    if parsed is None:
        return _http_error_message(exc, "work")
    code, message = parsed
    known = _WORK_ERROR_TEXT.get(code)
    if known:
        return known
    if message:
        return f"dispatchd returned {exc.code} for work: {message}"
    return _http_error_message(exc, "work")


def _run_work(raw: str) -> PluginResponse:
    if _http_config() is None:
        # Expected on a fresh install — control flow, not a Sentry event.
        return {"title": _WORK_TITLE, "text": _NOT_CONFIGURED_TEXT}

    url = _parse_work_command(raw)
    if url is None:
        return {"title": _WORK_TITLE, "text": _WORK_ERROR_TEXT["bad_request"]}

    try:
        envelope = _call_dispatchd("/v1/dispatch/work", method="POST", payload={"url": url})
        return {"title": _WORK_TITLE, "text": _format_work(envelope)}
    except urllib.error.HTTPError as exc:
        # 4xx here is the endpoint working as designed (bad paste, missing cap,
        # busy) — user-facing control flow, not an incident. Only 5xx is.
        if exc.code >= 500:
            capture(exc, plugin="dispatch", stage="work")
        return {"title": _WORK_TITLE, "text": _work_http_error_message(exc)}
    except Exception as exc:
        capture(exc, plugin="dispatch", stage="work")
        return {"title": _WORK_TITLE, "text": _http_error_message(exc, "work")}


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
    command = _COMMANDS.get(raw.lower())
    if command is None:
        return {"text": f"Unknown dispatch command: {text!r}"}
    return _run_command(command)
