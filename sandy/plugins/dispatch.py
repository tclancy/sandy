"""Sandy plugin: Dispatch status commands.

Read-only window into the Dispatch automation system. Fast, safe — no
agents are launched.

Commands:
  "dispatch status"  — current state from memory.md
  "dispatch check"   — dispatchd health and in-flight run status
  "dispatch pm"      — contents of PM Inbox.md

There is one backend: dispatchd's ``/v1/*`` read surface (metaframework
#326), reached over HTTP with HMAC-SHA256 request signing. The plugin is
configured by three env vars — ``DISPATCHD_BASE_URL``, ``DISPATCHD_KEY_ID``,
and ``DISPATCHD_SECRET``. When any of them is unset, every command returns
a friendly "not configured" message; there is no local-file fallback (Mac
dev runs dispatchd from the metaframework repo, same as production).
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
]

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


class EnvelopeData(TypedDict, total=False):
    """Union of the ``data`` payloads across the three read endpoints:
    ``text`` for /v1/dispatch/status and /v1/dispatch/pm-inbox,
    ``status`` + ``in_flight`` for /v1/health."""

    text: str
    status: str
    in_flight: InFlightRow | None


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


def _call_dispatchd(path: str) -> Envelope:
    """GET a dispatchd endpoint with HMAC-SHA256, return the parsed envelope.

    Signature and header shape are defined in ``docs/dispatchd.md``:
    ``HMAC-SHA256(secret, method \\n path \\n sha256(body) \\n nonce \\n ts)``.
    All 4xx/5xx responses raise ``urllib.error.HTTPError``, which the
    caller translates into a Sandy error message rather than propagate.
    """
    config = _http_config()
    if config is None:
        raise RuntimeError("dispatchd HTTP backend not configured")
    base_url, key_id, secret = config

    nonce = secrets.token_urlsafe(16)
    ts = str(int(time.time()))
    body = b""
    body_sha = hashlib.sha256(body).hexdigest()
    canonical = f"GET\n{path}\n{body_sha}\n{nonce}\n{ts}".encode()
    sig = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()

    req = urllib.request.Request(
        base_url + path,
        headers={
            "Authorization": f"HMAC {key_id}:{sig}",
            "X-Nonce": nonce,
            "X-Timestamp": ts,
            # Cloudflare's Browser Integrity Check (error 1010) bans the
            # default Python-urllib UA before the request reaches dispatchd.
            # Naming follows the dispatch-family convention set by
            # dispatchd-mcp/1.0 (metaframework oauth.py, same CF issue).
            "User-Agent": "dispatch-sandy/1.0",
        },
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
    command = _COMMANDS.get(text.lower().strip())
    if command is None:
        return {"text": f"Unknown dispatch command: {text!r}"}
    return _run_command(command)
