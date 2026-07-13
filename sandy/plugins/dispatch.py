"""Sandy plugin: Dispatch status commands.

Read-only window into the Dispatch automation system. Fast, safe — no
agents are launched.

Commands:
  "dispatch status"  — current state from memory.md
  "dispatch check"   — recent run activity and in-flight status
  "dispatch pm"      — contents of PM Inbox.md

The plugin has two backends:

- **HTTP (dispatchd)**: when ``DISPATCHD_BASE_URL``, ``DISPATCHD_KEY_ID``,
  and ``DISPATCHD_SECRET`` are all set, calls are signed with HMAC-SHA256
  and made against dispatchd's ``/v1/*`` read surface (metaframework #326).
  This is the homelab-Sandy path — it needs no Mac filesystem access.
- **Local files**: fallback for Mac-local dev when the HTTP env vars are
  not set. Reads ``memory.md`` / ``PM Inbox.md`` / ``logs/wake-*.log``
  directly, same as pre-#136 behavior.

When neither backend can produce a result (HTTP unreachable AND no local
files), each command returns a friendly explanation instead of the
generic "I'm not sure how to do that" fallback.
"""

from __future__ import annotations

import glob
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

name = "dispatch"
commands = [
    "dispatch status",
    "dispatch check",
    "dispatch pm",
]

# Default location — can be overridden by DISPATCH_OBSIDIAN_DIR env var
_DEFAULT_DISPATCH_DIR = Path.home() / "Documents/notes/tclancy/Dispatch"
_DEFAULT_METAFRAMEWORK_DIR = Path.home() / "Documents/work/metaframework"

_HTTP_TIMEOUT_SECONDS = 5


def _dispatch_dir() -> Path:
    return Path(os.environ.get("DISPATCH_OBSIDIAN_DIR", str(_DEFAULT_DISPATCH_DIR)))


def _metaframework_dir() -> Path:
    return Path(os.environ.get("DISPATCH_METAFRAMEWORK_DIR", str(_DEFAULT_METAFRAMEWORK_DIR)))


# ---------------------------------------------------------------------------
# HTTP backend (dispatchd HMAC bearer, docs/dispatchd.md)
# ---------------------------------------------------------------------------


def _http_config() -> tuple[str, str, str] | None:
    """Return (base_url, key_id, secret) if fully configured, else None.

    All three env vars must be set to opt in — a partial config falls back
    to local files rather than half-authenticating a request that will
    401. Trailing slash on ``DISPATCHD_BASE_URL`` is normalized so callers
    can set either shape.
    """
    base_url = os.environ.get("DISPATCHD_BASE_URL", "").strip().rstrip("/")
    key_id = os.environ.get("DISPATCHD_KEY_ID", "").strip()
    secret = os.environ.get("DISPATCHD_SECRET", "").strip()
    if not (base_url and key_id and secret):
        return None
    return base_url, key_id, secret


def _remote_backend_ok() -> bool:
    return _http_config() is not None


def _call_dispatchd(path: str) -> dict[str, Any]:
    """GET a dispatchd endpoint with HMAC-SHA256, return the parsed envelope.

    Signature and header shape are defined in ``docs/dispatchd.md``:
    ``HMAC-SHA256(secret, method \\n path \\n sha256(body) \\n nonce \\n ts)``.
    All 4xx/5xx responses raise ``urllib.error.HTTPError``, which the
    callers translate into a Sandy error message rather than propagate.
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
        },
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _remote_context() -> bool:
    """Return True if we cannot reach Dispatch state at all.

    True only when the HTTP backend is not configured AND neither of the
    local dirs exists. Pre-#136 behavior (Mac dev with no dispatchd) still
    resolves to False so the local-file readers run; homelab sandy with
    HTTP configured is False even though the dirs don't exist.
    """
    if _remote_backend_ok():
        return False
    return not _dispatch_dir().exists() and not _metaframework_dir().exists()


def _http_error_message(exc: Exception, kind: str) -> str:
    """Format a Sandy-friendly error for an HTTP call failure.

    Errors go into ``text`` (not ``code_text``) so Slack renders them
    inline. Keep the message short — full traceback lands in the daemon
    log, not in Slack.
    """
    if isinstance(exc, urllib.error.HTTPError):
        return f"dispatchd returned {exc.code} for {kind}."
    if isinstance(exc, urllib.error.URLError):
        return f"dispatchd unreachable ({exc.reason}) for {kind}."
    return f"dispatchd {kind} failed: {exc}"


# ---------------------------------------------------------------------------
# status — summary from memory.md
# ---------------------------------------------------------------------------


def _extract_current_status(raw: str) -> str:
    """Pull the ``## Current Status`` section, or first 20 lines as fallback."""
    match = re.search(r"## Current Status\n(.*?)(?=\n## |\Z)", raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    return "\n".join(raw.splitlines()[:20])


def _cmd_status_http() -> dict:
    try:
        envelope = _call_dispatchd("/v1/dispatch/status")
    except Exception as exc:
        return {"title": "Dispatch Status", "text": _http_error_message(exc, "status")}
    text = (envelope.get("data") or {}).get("text", "")
    if not text:
        return {"title": "Dispatch Status", "text": "memory.md is empty."}
    return {"title": "Dispatch Status", "text": _extract_current_status(text)}


def _cmd_status_local() -> dict:
    path = _dispatch_dir() / "memory.md"
    if not path.exists():
        return {"text": f"memory.md not found at {path}"}
    raw = path.read_text()
    match = re.search(r"## Current Status\n(.*?)(?=\n## |\Z)", raw, re.DOTALL)
    if match:
        return {"title": "Dispatch Status", "text": match.group(1).strip()}
    lines = raw.splitlines()[:20]
    return {"title": "Dispatch Memory (first 20 lines)", "text": "\n".join(lines)}


def _cmd_status() -> dict:
    """Read current status from Dispatch/memory.md (HTTP or local)."""
    if _remote_backend_ok():
        return _cmd_status_http()
    if _remote_context():
        return {
            "title": "Dispatch Status",
            "text": (
                "Sandy is running remotely and cannot reach Dispatch files on your Mac.\n"
                "Set DISPATCHD_BASE_URL / DISPATCHD_KEY_ID / DISPATCHD_SECRET to reach "
                "dispatchd, or check memory.md directly in Obsidian."
            ),
        }
    return _cmd_status_local()


# ---------------------------------------------------------------------------
# check — recent run activity
# ---------------------------------------------------------------------------


def _format_in_flight(row: dict[str, Any] | None) -> str:
    if not row:
        return "In-flight: none."
    session = row.get("session_type") or row.get("mode") or "?"
    pid = row.get("pid", "?")
    started = row.get("started_at", "?")
    return f"In-flight: {session} (pid {pid}, started {started})."


def _cmd_check_http() -> dict:
    """Homelab path: query /v1/health + /v1/in-flight."""
    lines: list[str] = []
    try:
        health = _call_dispatchd("/v1/health")
    except Exception as exc:
        return {"title": "Dispatch Activity", "text": _http_error_message(exc, "health")}
    health_data = health.get("data") or {}
    lines.append(f"Health: {health_data.get('status', '?')}")
    lines.append(_format_in_flight(health_data.get("in_flight")))
    as_of = health.get("as_of")
    if as_of:
        lines.append(f"As of: {as_of}")
    return {"title": "Dispatch Activity", "text": "\n".join(lines)}


def _cmd_check_local() -> dict:
    mf_dir = _metaframework_dir()
    logs_dir = mf_dir / "logs"

    lines: list[str] = []

    if logs_dir.exists():
        log_files = sorted(
            logs_dir.glob("wake-*.log"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        recent = log_files[:5]
        if recent:
            lines.append("Recent runs:")
            for log in recent:
                lines.append(f"  {log.name}")
        else:
            lines.append("No log files found.")
    else:
        lines.append(f"Logs directory not found: {logs_dir}")

    lock_files = glob.glob("/tmp/dispatch-*.lock")
    if lock_files:
        lines.append(f"\nActive lock(s): {', '.join(Path(f).name for f in lock_files)}")
    else:
        lines.append("\nNo active dispatch locks.")

    journal_dir = _dispatch_dir() / "Journal"
    if journal_dir.exists():
        journals = sorted(journal_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if journals:
            lines.append(f"\nLatest journal: {journals[0].name}")

    return {"title": "Dispatch Activity", "text": "\n".join(lines)}


def _cmd_check() -> dict:
    """Show recent dispatch runs / in-flight status."""
    if _remote_backend_ok():
        return _cmd_check_http()
    if _remote_context():
        return {
            "title": "Dispatch Activity",
            "text": (
                "Sandy is running remotely and cannot reach Dispatch logs on your Mac.\n"
                "Set DISPATCHD_BASE_URL / DISPATCHD_KEY_ID / DISPATCHD_SECRET to reach "
                "dispatchd."
            ),
        }
    return _cmd_check_local()


# ---------------------------------------------------------------------------
# pm — PM Inbox contents
# ---------------------------------------------------------------------------

# Strip YAML-style metadata blocks from the top
_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)


def _strip_pm_frontmatter(raw: str) -> str:
    return _FRONTMATTER_RE.sub("", raw.strip()).strip()


def _cmd_pm_http() -> dict:
    try:
        envelope = _call_dispatchd("/v1/dispatch/pm-inbox")
    except Exception as exc:
        return {"title": "PM Inbox", "text": _http_error_message(exc, "pm-inbox")}
    text = (envelope.get("data") or {}).get("text", "")
    if not text.strip():
        return {"title": "PM Inbox", "text": "PM Inbox is empty."}
    return {"title": "PM Inbox", "text": _strip_pm_frontmatter(text)}


def _cmd_pm_local() -> dict:
    path = _dispatch_dir() / "PM Inbox.md"
    if not path.exists():
        return {"text": f"PM Inbox.md not found at {path}"}

    raw = path.read_text().strip()
    if not raw:
        return {"text": "PM Inbox is empty."}

    return {"title": "PM Inbox", "text": _strip_pm_frontmatter(raw)}


def _cmd_pm() -> dict:
    """Show the contents of PM Inbox.md."""
    if _remote_backend_ok():
        return _cmd_pm_http()
    if _remote_context():
        return {
            "title": "PM Inbox",
            "text": (
                "Sandy is running remotely and cannot reach PM Inbox.md on your Mac.\n"
                "Set DISPATCHD_BASE_URL / DISPATCHD_KEY_ID / DISPATCHD_SECRET to reach "
                "dispatchd, or open PM Inbox.md directly in Obsidian."
            ),
        }
    return _cmd_pm_local()


# ---------------------------------------------------------------------------
# handle
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, str] = {
    "dispatch status": "_cmd_status",
    "dispatch check": "_cmd_check",
    "dispatch pm": "_cmd_pm",
}


def handle(text: str, actor: str) -> dict:
    cmd = text.lower().strip()
    fn_name = _DISPATCH.get(cmd)
    if fn_name is None:
        return {"text": f"Unknown dispatch command: {text!r}"}
    # globals() always refers to this module's namespace, regardless of how the
    # module was loaded. sys.modules[__name__] fails when the plugin loader
    # registers modules under a path-derived name that isn't in sys.modules.
    return globals()[fn_name]()
