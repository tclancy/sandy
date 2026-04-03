"""Sandy plugin: IT Guy homelab deployment.

Wraps the ``itguy`` CLI for deploying and listing homelab services via Slack.

Commands:
  "itguy list"          — show all configured services and their strategies
  "itguy deploy <svc>"  — deploy a service (uses strategy default)
  "itguy force <svc>"   — deploy a service with --force (always recreates container)

Requires ``itguy`` to be installed and on PATH. Returns a friendly error when
itguy is not available (e.g. Sandy running in a remote Docker container).
"""

from __future__ import annotations

import shutil
import subprocess

name = "itguy"
commands = ["itguy list", "itguy deploy", "itguy force"]

_ITGUY_CMD = "itguy"


def _available() -> bool:
    return shutil.which(_ITGUY_CMD) is not None


def _run(*args: str) -> dict:
    """Run an itguy subcommand and return a Sandy response dict."""
    if not _available():
        return {
            "title": "IT Guy",
            "text": (
                "itguy is not available on this host. "
                "Install it on your Mac with: uv pip install -e /path/to/itguy"
            ),
        }
    try:
        result = subprocess.run(
            [_ITGUY_CMD, *args],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"title": "IT Guy", "text": "Error: itguy timed out after 120s."}

    if result.returncode != 0:
        stderr = result.stderr.strip()
        msg = stderr or f"itguy exited with code {result.returncode}"
        return {"title": "IT Guy", "text": f"Error: {msg}"}

    output = result.stdout.strip()
    return {"title": "IT Guy", "text": output or "(no output)"}


def handle(text: str, actor: str) -> dict:
    cmd = text.lower().strip()

    if cmd == "itguy list":
        return _run("list", "--format", "slack")

    if cmd.startswith("itguy deploy"):
        service = cmd[len("itguy deploy") :].strip()
        if not service:
            return {"title": "IT Guy", "text": "Usage: itguy deploy <service>"}
        return _run("deploy", service)

    if cmd.startswith("itguy force"):
        service = cmd[len("itguy force") :].strip()
        if not service:
            return {"title": "IT Guy", "text": "Usage: itguy force <service>"}
        return _run("deploy", service, "--force")

    return {"title": "IT Guy", "text": f"Unknown itguy command: {text!r}"}
