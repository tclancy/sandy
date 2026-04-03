"""Sandy plugin: Estimated Taxes — tax summary via Slack.

Read-only access to the estimatedtaxes CLI. Recording income stays as a
direct CLI operation — this plugin is intentionally limited to queries.

Commands:
  "tax summary"   — current year income, estimated tax, and quarterly status
  "tax list"      — list all recorded income entries

Requires ``estimatedtaxes`` to be installed and on PATH.
Returns a friendly error when not available (e.g. Sandy running remotely).
"""

from __future__ import annotations

import shutil
import subprocess

name = "estimatedtaxes"
commands = ["tax summary", "tax list"]

_TAX_CMD = "estimatedtaxes"


def _available() -> bool:
    return shutil.which(_TAX_CMD) is not None


def _run(*args: str) -> dict:
    """Run an estimatedtaxes subcommand and return a Sandy response dict."""
    if not _available():
        return {
            "title": "Taxes",
            "text": (
                "estimatedtaxes is not available on this host. "
                "Install it on the homelab with: uv pip install -e /home/tom/sources/irs"
            ),
        }
    try:
        result = subprocess.run(
            [_TAX_CMD, *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {"title": "Taxes", "text": "Error: estimatedtaxes timed out after 30s."}

    if result.returncode != 0:
        stderr = result.stderr.strip()
        msg = stderr or f"estimatedtaxes exited with code {result.returncode}"
        return {"title": "Taxes", "text": f"Error: {msg}"}

    output = result.stdout.strip()
    return {"title": "Taxes", "text": output or "(no output)"}


def handle(text: str, actor: str) -> dict:
    cmd = text.lower().strip()

    if cmd == "tax summary":
        return _run("summarize")

    if cmd == "tax list":
        return _run("list")

    return {"title": "Taxes", "text": f"Unknown tax command: {text!r}"}
