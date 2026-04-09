"""Shared printer utility: download a PDF from a URL and send it to the local printer.

Any plugin can return a ``pdf_url`` key in its response dict and the Sandy
CLI will automatically call ``print_pdf`` to send it to the configured printer.

Printer name is read from the ``SANDY_PRINTER`` environment variable, which
can be set in ``sandy.toml`` under the ``[printer]`` or global section.
Run ``lpstat -p`` to list available printers.

**Direct IPP URI printing** (recommended for Linux homelab):
Set ``SANDY_PRINTER`` to a full IPP URI, e.g.::

    SANDY_PRINTER = "ipp://192.168.1.50/ipp/print"

This bypasses CUPS entirely and prints directly to the printer by IP using
the IPP protocol over HTTP. No CUPS registration required — works out of
the box on Linux without ``lpadmin``.

For CUPS-managed printers, use the queue name (``lpstat -p`` to list them).
"""

import http.client
import logging
import os
import struct
import subprocess
import tempfile
import urllib.parse

import requests

logger = logging.getLogger(__name__)

_DEFAULT_PRINTER = "Brother_MFC_L2750DW_series"


def _is_ipp_uri(printer: str) -> bool:
    """Return True if *printer* looks like an IPP or IPPS URI."""
    return printer.startswith("ipp://") or printer.startswith("ipps://")


def _build_lp_command(printer: str, file_path: str) -> list[str]:
    """Return the lp command for the given CUPS queue name and file.

    For CUPS-registered queue names only. Use ``_ipp_print_direct`` for
    IPP URIs — ``lp -d`` does not accept raw IPP URIs on all Linux systems.
    """
    return ["lp", "-d", printer, file_path]


def _pack_ipp_attr(tag: int, name: str, value: bytes) -> bytes:
    """Pack a single IPP attribute (tag + name + value)."""
    name_bytes = name.encode("ascii")
    return (
        bytes([tag])
        + struct.pack(">H", len(name_bytes))
        + name_bytes
        + struct.pack(">H", len(value))
        + value
    )


def _ipp_print_direct(ipp_uri: str, pdf_path: str) -> tuple[bool, str]:
    """Send a print-job directly to an IPP printer over HTTP, bypassing CUPS.

    Implements a minimal IPP 1.1 Print-Job request (RFC 8011).  Works with any
    IPP-capable printer accessible by IP — no CUPS queue registration needed.

    Args:
        ipp_uri: Full IPP URI, e.g. ``ipp://192.168.1.50/ipp/print``.
        pdf_path: Local path to the PDF file to send.

    Returns:
        ``(True, "")`` on success, ``(False, detail)`` on failure.
    """
    parsed = urllib.parse.urlparse(ipp_uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 631
    path = parsed.path or "/ipp/print"
    use_ssl = ipp_uri.startswith("ipps://")

    # Build IPP 1.1 Print-Job request body (RFC 8011 §4.4.1)
    attrs = b"\x01"  # operation-attributes-tag
    attrs += _pack_ipp_attr(0x47, "attributes-charset", b"utf-8")
    attrs += _pack_ipp_attr(0x48, "attributes-natural-language", b"en-us")
    attrs += _pack_ipp_attr(0x45, "printer-uri", ipp_uri.encode("ascii"))
    attrs += _pack_ipp_attr(0x42, "requesting-user-name", b"sandy")
    attrs += _pack_ipp_attr(0x42, "job-name", b"Sandy Print Job")
    attrs += _pack_ipp_attr(0x49, "document-format", b"application/pdf")
    attrs += b"\x03"  # end-of-attributes-tag

    # IPP/1.1 header: version(2) + operation-id(2) + request-id(4)
    header = struct.pack(">BBHI", 1, 1, 0x0002, 1)

    with open(pdf_path, "rb") as f:
        pdf_data = f.read()

    body = header + attrs + pdf_data

    try:
        if use_ssl:
            import ssl

            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                host, port, timeout=30, context=ctx
            )
        else:
            conn = http.client.HTTPConnection(host, port, timeout=30)

        try:
            conn.request(
                "POST",
                path,
                body,
                {
                    "Content-Type": "application/ipp",
                    "Content-Length": str(len(body)),
                },
            )
            response = conn.getresponse()
            resp_data = response.read()
        finally:
            conn.close()

        if response.status not in (200, 202):
            return False, f"IPP server returned HTTP {response.status}"

        # Parse IPP response status code (bytes 2–3 of the response body).
        # RFC 8011 successful codes: 0x0000, 0x0001, 0x0002.
        if len(resp_data) >= 4:
            status_code = struct.unpack(">H", resp_data[2:4])[0]
            if status_code in (0x0000, 0x0001, 0x0002):
                return True, ""
            return False, f"IPP status {status_code:#06x}"

        # HTTP 200/202 with no parseable IPP response — assume success
        return True, ""
    except Exception as exc:
        return False, f"IPP direct print failed: {exc}"


def _discover_ipp_uris() -> list[str]:
    """Try to discover available IPP printer URIs via ``lpinfo -v``.

    Returns a list of IPP URIs (may be empty if discovery fails or finds none).
    Runs ``lpinfo -v`` with a short timeout — safe to call even if CUPS is not
    running (it fails gracefully).
    """
    try:
        result = subprocess.run(
            ["lpinfo", "-v"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        uris = []
        for line in result.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[1].startswith(("ipp://", "ipps://")):
                uris.append(parts[1].strip())
        return uris
    except Exception:
        return []


def _lp_print(printer: str, file_path: str) -> tuple[bool, str]:
    """Print via ``lp -d <printer>`` for CUPS-registered queue names.

    When the printer is not found in CUPS, automatically attempts IPP discovery
    via ``lpinfo -v`` and retries with any discovered IPP URI that matches the
    printer name.  This allows printing to succeed even when CUPS has no
    registered queue, as long as the printer is accessible on the network.

    Returns ``(True, "")`` on success, ``(False, detail)`` on failure.
    """
    cmd = _build_lp_command(printer, file_path)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return True, ""

    stderr = (result.stderr or result.stdout or "").strip()
    cups_detail = f"lp exited {result.returncode}"
    if stderr:
        cups_detail += f": {stderr}"

    # When the printer isn't found in CUPS, try IPP auto-discovery.
    # This handles the common Linux homelab case where the printer is on the
    # network but not registered in CUPS.
    if "does not exist" in stderr or "not found" in stderr.lower():
        logger.info(
            "CUPS printer %r not found — attempting IPP auto-discovery via lpinfo -v", printer
        )
        discovered = _discover_ipp_uris()
        if discovered:
            logger.info("Discovered IPP URIs: %s", discovered)
            # Try discovered URIs — prefer ones that contain the printer name
            name_lower = printer.lower().replace("_", "-").replace(" ", "-")
            ordered = sorted(
                discovered,
                key=lambda u: 0 if name_lower.split("_")[0][:6] in u.lower() else 1,
            )
            for ipp_uri in ordered:
                logger.info("Trying discovered IPP URI: %s", ipp_uri)
                ok, detail = _ipp_print_direct(ipp_uri, file_path)
                if ok:
                    logger.info(
                        "Auto-discovered printer succeeded via %s. "
                        "Set SANDY_PRINTER = %r in sandy.toml to skip this step.",
                        ipp_uri,
                        ipp_uri,
                    )
                    return True, ""
            # Discovery found URIs but none worked
            uri_list = ", ".join(discovered[:3])
            return (
                False,
                f"{cups_detail}. IPP discovery found {len(discovered)} printer(s) ({uri_list}) "
                f"but all failed. Set SANDY_PRINTER to one of these URIs in sandy.toml.",
            )

    # No discovery or no printers found — give a clear action hint
    action_hint = (
        " To fix: find your printer's IP on your router, then add "
        'SANDY_PRINTER = "ipp://PRINTER_IP/ipp/print" to sandy.toml.'
    )
    available = _list_cups_printers()
    if available:
        cups_detail += f". CUPS printers: {available}"
    else:
        cups_detail += "." + action_hint
    return False, cups_detail


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

    If *printer* is an IPP URI (``ipp://`` or ``ipps://``), the job is sent
    directly via HTTP/IPP without going through CUPS.  For CUPS queue names,
    ``lp -d`` is used instead.

    Args:
        url: Direct URL to a PDF file.
        printer: Printer name or IPP URI. Falls back to the ``SANDY_PRINTER``
            env var, then the built-in default CUPS queue name.

    Returns:
        A ``(success, detail)`` tuple. *success* is True on success, False on
        any failure. *detail* is an empty string on success, or a short
        diagnostic message on failure.
    """
    if printer is None:
        printer = os.environ.get("SANDY_PRINTER", _DEFAULT_PRINTER)

    logger.info("Printing PDF from %s to '%s'", url, printer)

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(response.content)
            tmp_path = f.name

        try:
            if _is_ipp_uri(printer):
                success, detail = _ipp_print_direct(printer, tmp_path)
            else:
                success, detail = _lp_print(printer, tmp_path)

            if not success:
                logger.error("Print failed (printer='%s', url=%s): %s", printer, url, detail)
                return False, detail
        finally:
            os.unlink(tmp_path)

        logger.info("Printed PDF from %s to '%s'", url, printer)
        return True, ""
    except Exception as exc:
        detail = str(exc)
        logger.error("Print failed (printer='%s', url=%s): %s", printer, url, detail)
        return False, detail
