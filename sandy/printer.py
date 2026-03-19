"""Shared printer utility: download a PDF from a URL and send it to the local printer.

Any plugin can return a ``pdf_url`` key in its response dict and the Sandy
CLI will automatically call ``print_pdf`` to send it to the configured printer.

Printer name is read from the ``SANDY_PRINTER`` environment variable, which
can be set in ``sandy.toml`` under the ``[printer]`` or global section.
Run ``lpstat -p`` to list available printers.
"""

import os
import subprocess
import tempfile

import requests

_DEFAULT_PRINTER = "Brother_MFC_L2750DW_series"


def print_pdf(url: str, printer: str | None = None) -> bool:
    """Download the PDF at *url* and send it to the printer.

    Args:
        url: Direct URL to a PDF file.
        printer: Printer name for ``lpr -P``. Falls back to the
            ``SANDY_PRINTER`` env var, then the built-in default.

    Returns:
        True on success, False if any step fails.
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
            subprocess.run(["lpr", "-P", printer, tmp_path], check=True)
        finally:
            os.unlink(tmp_path)
            ps_path = tmp_path.replace(".pdf", ".ps")
            if os.path.exists(ps_path):
                os.unlink(ps_path)

        return True
    except Exception:
        return False
