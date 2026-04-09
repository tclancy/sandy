"""Sandy built-in: printer diagnostics.

Reports the printer configuration and tests connectivity.

Commands:
  "printer status"  — show current printer config and connectivity
"""

from __future__ import annotations

import os
import socket

from sandy.printer import (
    _DEFAULT_PRINTER,
    _discover_ipp_uris,
    _is_ipp_uri,
    _list_cups_printers,
)

name = "printer"
commands = ["printer status"]


def _test_ipp_connectivity(ipp_uri: str, timeout: int = 5) -> tuple[bool, str]:
    """Try a TCP connection to the IPP printer's host:port.

    Returns (reachable, detail_message).
    This is a connectivity check only — it does not send an IPP request.
    """
    try:
        from urllib.parse import urlparse

        parsed = urlparse(ipp_uri)
        host = parsed.hostname or "localhost"
        port = parsed.port or 631
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True, f"{host}:{port} reachable"
    except OSError as exc:
        return False, str(exc)


def handle(text: str, actor: str) -> dict:
    cmd = text.lower().strip()

    if cmd == "printer status":
        return _printer_status()

    return {"title": "Printer", "text": f"Unknown printer command: {text!r}"}


def _printer_status() -> dict:
    printer_name = os.environ.get("SANDY_PRINTER", _DEFAULT_PRINTER)
    is_ipp = _is_ipp_uri(printer_name)

    lines = []
    lines.append(f"*SANDY_PRINTER:* `{printer_name}`")

    if is_ipp:
        lines.append("*Type:* IPP direct (bypasses CUPS)")
        reachable, detail = _test_ipp_connectivity(printer_name)
        if reachable:
            lines.append(f"*Connectivity:* ✓ {detail}")
        else:
            lines.append(f"*Connectivity:* ✗ {detail}")
            lines.append("_Check the printer's IP and that it's powered on._")
    else:
        lines.append("*Type:* CUPS queue name")
        lines.append(
            '_To bypass CUPS, set `SANDY_PRINTER = "ipp://PRINTER_IP/ipp/print"` in sandy.toml._'
        )
        cups_printers = _list_cups_printers()
        if cups_printers:
            lines.append(f"*CUPS printers available:* {cups_printers}")
        else:
            lines.append("*CUPS printers:* none found (run `lpstat -p` to check)")

        # Try auto-discovery even for CUPS printers
        discovered = _discover_ipp_uris()
        if discovered:
            uris = ", ".join(f"`{u}`" for u in discovered[:5])
            lines.append(f"*IPP printers discovered via lpinfo:* {uris}")
            lines.append("_Set one of these as `SANDY_PRINTER` to bypass CUPS._")

    return {
        "title": "Printer Status",
        "text": "\n".join(lines),
    }
