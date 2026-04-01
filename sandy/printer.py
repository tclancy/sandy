"""Shared printer utility: download a PDF from a URL and send it to the local printer.

Any plugin can return a ``pdf_url`` key in its response dict and the Sandy
CLI will automatically call ``print_pdf`` to send it to the configured printer.

Printer name is read from the ``SANDY_PRINTER`` environment variable, which
can be set in ``sandy.toml`` under the ``[printer]`` or global section.
Run ``lpstat -p`` to list available printers.

**Direct IPP URI printing** (recommended for Linux homelab):
Set ``SANDY_PRINTER`` to a full IPP URI, e.g.::

    SANDY_PRINTER = "ipp://192.168.1.50/ipp/print"

This bypasses CUPS queue lookup and prints directly to the printer by IP,
which avoids mDNS/Bonjour hostname resolution issues on Linux.
"""

import logging
import os
import subprocess
import tempfile

import requests

logger = logging.getLogger(__name__)

_DEFAULT_PRINTER = "Brother_MFC_L2750DW_series"


def _is_ipp_uri(printer: str) -> bool:
    return printer.startswith("ipp://") or printer.startswith("ipps://")


def _build_lp_command(printer: str, file_path: str) -> list[str]:
    """Return the lp/lpr command for the given printer and file.

    If *printer* is an IPP URI, uses ``lp -d URI`` for direct network printing.
    Otherwise falls back to ``lpr -P name`` for a CUPS-named queue.
    """
    if _is_ipp_uri(printer):
        return ["lp", "-d", printer, file_path]
    return ["lpr", "-P", printer, file_path]


def _list_cups_printers() -> str | None:
    """Return a comma-separated list of CUPS printer names, or None on failure."""
    try:
        result = subprocess.run(
            ["lpstat", "-p"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        names = [
            line.split()[1] for line in result.stdout.splitlines() if line.startswith("printer ")
        ]
        return ", ".join(names) if names else None
    except Exception:
        return None


def print_pdf(url: str, printer: str | None = None) -> tuple[bool, str]:
    """Download the PDF at *url* and send it to the printer.

    Args:
        url: Direct URL to a PDF file.
        printer: Printer name or IPP URI for ``lp``/``lpr``. Falls back to the
            ``SANDY_PRINTER`` env var, then the built-in default.

    Returns:
        A ``(success, detail)`` tuple. *success* is True on success, False on
        any failure. *detail* is an empty string on success, or a short
        diagnostic message on failure.
    """
    if printer is None:
        printer = os.environ.get("SANDY_PRINTER", _DEFAULT_PRINTER)

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(response.content)
            tmp_path = f.name

        try:
            cmd = _build_lp_command(printer, tmp_path)
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                stderr = (result.stderr or result.stdout or "").strip()
                detail = f"lpr/lp exited {result.returncode}"
                if stderr:
                    detail += f": {stderr}"
                available = _list_cups_printers()
                if available:
                    detail += f". CUPS printers: {available}"
                logger.error("Print failed (printer='%s', url=%s): %s", printer, url, detail)
                return False, detail
        finally:
            os.unlink(tmp_path)
            ps_path = tmp_path.replace(".pdf", ".ps")
            if os.path.exists(ps_path):
                os.unlink(ps_path)

        logger.info("Printed PDF from %s to printer '%s'", url, printer)
        return True, ""
    except Exception as exc:
        detail = str(exc)
        logger.error("Print failed (printer='%s', url=%s): %s", printer, url, detail)
        return False, detail
