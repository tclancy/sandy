"""Sandy plugin: Dispatch status commands.

Read-only window into the Dispatch automation system. Fast, safe — no
agents are launched.

Commands:
  "dispatch status" / "status"  — current state from memory.md
  "dispatch check"  / "check"   — recent run activity and lock status
  "dispatch pm"     / "pm"      — contents of PM Inbox.md

The plugin reads files directly so it returns instantly, unlike the
dispatch CLI modes that launch full Claude agent sessions.

When Sandy is running remotely (e.g. homelab Docker container) and cannot
reach the Mac's Dispatch files, each command returns a friendly explanation
instead of the generic "I'm not sure how to do that" fallback.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

name = "dispatch"
commands = [
    "dispatch status",
    "dispatch check",
    "dispatch pm",
    "status",
    "check",
    "pm",
]

# Default location — can be overridden by DISPATCH_OBSIDIAN_DIR env var
_DEFAULT_DISPATCH_DIR = Path.home() / "Documents/notes/tclancy/Dispatch"
_DEFAULT_METAFRAMEWORK_DIR = Path.home() / "Documents/work/metaframework"


def _dispatch_dir() -> Path:
    return Path(os.environ.get("DISPATCH_OBSIDIAN_DIR", str(_DEFAULT_DISPATCH_DIR)))


def _metaframework_dir() -> Path:
    return Path(os.environ.get("DISPATCH_METAFRAMEWORK_DIR", str(_DEFAULT_METAFRAMEWORK_DIR)))


def _remote_context() -> bool:
    """Return True if neither key Dispatch directory is reachable.

    When Sandy is running on a remote host (e.g. homelab Docker container) the
    Obsidian vault and metaframework checkout aren't mounted.  Rather than
    returning raw path-not-found errors for every command, we detect this once
    and return a friendly explanation.
    """
    return not _dispatch_dir().exists() and not _metaframework_dir().exists()


# ---------------------------------------------------------------------------
# status — summary from memory.md
# ---------------------------------------------------------------------------

# Lines we want from memory.md: section headers and "IN-PROGRESS / BLOCKED" bullets
_STATUS_RE = re.compile(
    r"(##\s+Current Status|^\s*-\s+\*\*(?:IN-PROGRESS|BLOCKED|READY|complete)\*\*.*)",
    re.IGNORECASE | re.MULTILINE,
)


def _cmd_status() -> dict:
    """Read current status from Dispatch/memory.md."""
    if _remote_context():
        return {
            "title": "Dispatch Status",
            "text": (
                "Sandy is running remotely and cannot reach Dispatch files on your Mac.\n"
                "Check memory.md directly in Obsidian."
            ),
        }

    path = _dispatch_dir() / "memory.md"
    if not path.exists():
        return {"text": f"memory.md not found at {path}"}

    raw = path.read_text()

    # Extract the ## Current Status section
    match = re.search(r"## Current Status\n(.*?)(?=\n## |\Z)", raw, re.DOTALL)
    if match:
        section = match.group(1).strip()
        return {
            "title": "Dispatch Status",
            "text": section,
        }

    # Fallback: return first 20 lines
    lines = raw.splitlines()[:20]
    return {"title": "Dispatch Memory (first 20 lines)", "text": "\n".join(lines)}


# ---------------------------------------------------------------------------
# check — recent run activity
# ---------------------------------------------------------------------------


def _cmd_check() -> dict:
    """Show recent dispatch runs and lock status."""
    if _remote_context():
        return {
            "title": "Dispatch Activity",
            "text": (
                "Sandy is running remotely and cannot reach Dispatch logs on your Mac.\n"
                "Check the metaframework logs directory directly."
            ),
        }

    mf_dir = _metaframework_dir()
    logs_dir = mf_dir / "logs"

    lines: list[str] = []

    # Last 5 log files by modification time
    if logs_dir.exists():
        log_files = sorted(
            logs_dir.glob("wake-*.log"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        recent = log_files[:5]
        if recent:
            lines.append("Recent runs:")
            for log in recent:
                # Extract the mode from the filename: wake-YYYY-MM-DD_HH-MM-SS.log
                lines.append(f"  {log.name}")
        else:
            lines.append("No log files found.")
    else:
        lines.append(f"Logs directory not found: {logs_dir}")

    # Active locks
    import glob

    lock_files = glob.glob("/tmp/dispatch-*.lock")
    if lock_files:
        lines.append(f"\nActive lock(s): {', '.join(Path(f).name for f in lock_files)}")
    else:
        lines.append("\nNo active dispatch locks.")

    # Most recent journal entry filename
    journal_dir = _dispatch_dir() / "Journal"
    if journal_dir.exists():
        journals = sorted(journal_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if journals:
            lines.append(f"\nLatest journal: {journals[0].name}")

    return {"title": "Dispatch Activity", "text": "\n".join(lines)}


# ---------------------------------------------------------------------------
# pm — PM Inbox contents
# ---------------------------------------------------------------------------

# Strip YAML-style metadata blocks from the top
_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)


def _cmd_pm() -> dict:
    """Show the contents of PM Inbox.md."""
    if _remote_context():
        return {
            "title": "PM Inbox",
            "text": (
                "Sandy is running remotely and cannot reach PM Inbox.md on your Mac.\n"
                "Open PM Inbox.md directly in Obsidian."
            ),
        }

    path = _dispatch_dir() / "PM Inbox.md"
    if not path.exists():
        return {"text": f"PM Inbox.md not found at {path}"}

    raw = path.read_text().strip()
    if not raw:
        return {"text": "PM Inbox is empty."}

    # Strip frontmatter if present
    raw = _FRONTMATTER_RE.sub("", raw).strip()

    return {"title": "PM Inbox", "text": raw}


# ---------------------------------------------------------------------------
# handle
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, str] = {
    "dispatch status": "_cmd_status",
    "status": "_cmd_status",
    "dispatch check": "_cmd_check",
    "check": "_cmd_check",
    "dispatch pm": "_cmd_pm",
    "pm": "_cmd_pm",
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
