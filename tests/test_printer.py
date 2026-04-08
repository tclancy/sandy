"""Tests for sandy.printer — shared PDF printing utility."""

import struct
from unittest.mock import MagicMock, patch

from sandy import printer
from sandy.printer import (
    _build_lp_command,
    _ipp_print_direct,
    _is_ipp_uri,
    _lp_print,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response():
    mock = MagicMock()
    mock.content = b"%PDF fake content"
    return mock


def _mock_run_success():
    mock = MagicMock()
    mock.returncode = 0
    mock.stderr = ""
    mock.stdout = ""
    return mock


def _mock_run_failure(stderr="lp: Error - printer not found", returncode=1):
    mock = MagicMock()
    mock.returncode = returncode
    mock.stderr = stderr
    mock.stdout = ""
    return mock


def _ipp_ok_response() -> bytes:
    """Minimal valid IPP 1.1 response body with successful-ok status."""
    # version(2) + status-code 0x0000(2) + request-id(4) + end-attrs(1)
    return struct.pack(">BBHIB", 1, 1, 0x0000, 1, 0x03)


# ---------------------------------------------------------------------------
# _is_ipp_uri
# ---------------------------------------------------------------------------


def test_is_ipp_uri_ipp():
    assert _is_ipp_uri("ipp://192.168.1.50/ipp/print") is True


def test_is_ipp_uri_ipps():
    assert _is_ipp_uri("ipps://printer.local/ipp/print") is True


def test_is_ipp_uri_cups_name():
    assert _is_ipp_uri("Brother_MFC_L2750DW_series") is False


def test_is_ipp_uri_empty():
    assert _is_ipp_uri("") is False


# ---------------------------------------------------------------------------
# _build_lp_command
# ---------------------------------------------------------------------------


def test_build_lp_command_named_printer():
    cmd = _build_lp_command("MyPrinter", "/tmp/file.pdf")
    assert cmd == ["lp", "-d", "MyPrinter", "/tmp/file.pdf"]


# ---------------------------------------------------------------------------
# _lp_print
# ---------------------------------------------------------------------------


def test_lp_print_success(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF")
    with patch("sandy.printer.subprocess.run", return_value=_mock_run_success()):
        success, detail = _lp_print("MyPrinter", str(pdf))
    assert success is True
    assert detail == ""


def test_lp_print_failure_includes_stderr(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF")
    with (
        patch(
            "sandy.printer.subprocess.run",
            return_value=_mock_run_failure("lp: Error - The printer or class does not exist."),
        ),
        patch("sandy.printer._list_cups_printers", return_value=None),
    ):
        success, detail = _lp_print("BadPrinter", str(pdf))
    assert success is False
    assert "The printer or class does not exist" in detail


def test_lp_print_failure_includes_cups_list(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF")
    with (
        patch("sandy.printer.subprocess.run", return_value=_mock_run_failure()),
        patch("sandy.printer._list_cups_printers", return_value="Brother_MFC_L2750DW"),
    ):
        success, detail = _lp_print("BadPrinter", str(pdf))
    assert success is False
    assert "Brother_MFC_L2750DW" in detail


# ---------------------------------------------------------------------------
# _ipp_print_direct
# ---------------------------------------------------------------------------


def _mock_ipp_connection(status=200, body=None):
    """Build a mock http.client.HTTPConnection that returns an IPP response."""
    if body is None:
        body = _ipp_ok_response()
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = body
    mock_conn = MagicMock()
    mock_conn.getresponse.return_value = mock_resp
    return mock_conn


def test_ipp_print_direct_success(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF")
    mock_conn = _mock_ipp_connection()
    with patch("sandy.printer.http.client.HTTPConnection", return_value=mock_conn):
        success, detail = _ipp_print_direct("ipp://192.168.1.50/ipp/print", str(pdf))
    assert success is True
    assert detail == ""
    mock_conn.request.assert_called_once()
    call_args = mock_conn.request.call_args
    assert call_args[0][0] == "POST"
    assert call_args[0][1] == "/ipp/print"
    headers = call_args[0][3]
    assert headers["Content-Type"] == "application/ipp"


def test_ipp_print_direct_sends_pdf_data(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf_content = b"%PDF-1.4 fake content"
    pdf.write_bytes(pdf_content)
    mock_conn = _mock_ipp_connection()
    with patch("sandy.printer.http.client.HTTPConnection", return_value=mock_conn):
        _ipp_print_direct("ipp://192.168.1.50/ipp/print", str(pdf))
    body = mock_conn.request.call_args[0][2]
    assert pdf_content in body


def test_ipp_print_direct_http_error(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF")
    mock_conn = _mock_ipp_connection(status=503, body=b"")
    with patch("sandy.printer.http.client.HTTPConnection", return_value=mock_conn):
        success, detail = _ipp_print_direct("ipp://192.168.1.50/ipp/print", str(pdf))
    assert success is False
    assert "503" in detail


def test_ipp_print_direct_ipp_error_status(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF")
    # IPP 1.1 response with status 0x0400 (client-error-bad-request)
    bad_body = struct.pack(">BBHIB", 1, 1, 0x0400, 1, 0x03)
    mock_conn = _mock_ipp_connection(status=200, body=bad_body)
    with patch("sandy.printer.http.client.HTTPConnection", return_value=mock_conn):
        success, detail = _ipp_print_direct("ipp://192.168.1.50/ipp/print", str(pdf))
    assert success is False
    assert "0x0400" in detail


def test_ipp_print_direct_connection_error(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF")
    with patch(
        "sandy.printer.http.client.HTTPConnection", side_effect=OSError("Connection refused")
    ):
        success, detail = _ipp_print_direct("ipp://192.168.1.50/ipp/print", str(pdf))
    assert success is False
    assert "Connection refused" in detail


def test_ipp_print_direct_uses_correct_host_port(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF")
    mock_conn = _mock_ipp_connection()
    with patch("sandy.printer.http.client.HTTPConnection", return_value=mock_conn) as mock_cls:
        _ipp_print_direct("ipp://192.168.1.50:631/ipp/print", str(pdf))
    mock_cls.assert_called_once_with("192.168.1.50", 631, timeout=30)


# ---------------------------------------------------------------------------
# print_pdf — dispatch: IPP URI uses direct IPP, queue name uses lp
# ---------------------------------------------------------------------------


def test_print_pdf_ipp_uri_uses_direct_ipp(tmp_path, monkeypatch):
    """IPP URI destinations must bypass lp and use _ipp_print_direct."""
    monkeypatch.setenv("SANDY_PRINTER", "ipp://192.168.1.50/ipp/print")
    mock_file = MagicMock()
    mock_file.name = str(tmp_path / "puzzle.pdf")
    with (
        patch("sandy.printer.requests.get", return_value=_mock_response()),
        patch("sandy.printer._ipp_print_direct", return_value=(True, "")) as mock_ipp,
        patch("sandy.printer._lp_print") as mock_lp,
        patch("sandy.printer.tempfile.NamedTemporaryFile") as mock_tmp,
        patch("sandy.printer.os.unlink"),
        patch("sandy.printer.os.path.exists", return_value=False),
    ):
        mock_tmp.return_value.__enter__.return_value = mock_file
        success, detail = printer.print_pdf("https://example.com/puzzle.pdf")
    assert success is True
    mock_ipp.assert_called_once()
    mock_lp.assert_not_called()


def test_print_pdf_cups_name_uses_lp(tmp_path, monkeypatch):
    """CUPS queue names must go through lp, not direct IPP."""
    monkeypatch.setenv("SANDY_PRINTER", "Brother_MFC_L2750DW_series")
    mock_file = MagicMock()
    mock_file.name = str(tmp_path / "puzzle.pdf")
    with (
        patch("sandy.printer.requests.get", return_value=_mock_response()),
        patch("sandy.printer._ipp_print_direct") as mock_ipp,
        patch("sandy.printer._lp_print", return_value=(True, "")) as mock_lp,
        patch("sandy.printer.tempfile.NamedTemporaryFile") as mock_tmp,
        patch("sandy.printer.os.unlink"),
        patch("sandy.printer.os.path.exists", return_value=False),
    ):
        mock_tmp.return_value.__enter__.return_value = mock_file
        success, _ = printer.print_pdf("https://example.com/puzzle.pdf")
    assert success is True
    mock_lp.assert_called_once()
    mock_ipp.assert_not_called()


# ---------------------------------------------------------------------------
# print_pdf — legacy success/failure paths (CUPS queue name)
# ---------------------------------------------------------------------------


def test_print_pdf_returns_true_on_success(tmp_path):
    mock_file = MagicMock()
    mock_file.name = str(tmp_path / "puzzle.pdf")
    with (
        patch("sandy.printer.requests.get", return_value=_mock_response()),
        patch("sandy.printer._lp_print", return_value=(True, "")),
        patch("sandy.printer.tempfile.NamedTemporaryFile") as mock_tmp,
        patch("sandy.printer.os.unlink"),
        patch("sandy.printer.os.path.exists", return_value=False),
    ):
        mock_tmp.return_value.__enter__.return_value = mock_file
        success, detail = printer.print_pdf("https://example.com/puzzle.pdf")
    assert success is True
    assert detail == ""


def test_print_pdf_accepts_explicit_printer(tmp_path):
    mock_file = MagicMock()
    mock_file.name = str(tmp_path / "puzzle.pdf")
    with (
        patch("sandy.printer.requests.get", return_value=_mock_response()),
        patch("sandy.printer._lp_print", return_value=(True, "")) as mock_lp,
        patch("sandy.printer.tempfile.NamedTemporaryFile") as mock_tmp,
        patch("sandy.printer.os.unlink"),
        patch("sandy.printer.os.path.exists", return_value=False),
    ):
        mock_tmp.return_value.__enter__.return_value = mock_file
        printer.print_pdf("https://example.com/puzzle.pdf", printer="Explicit_Printer")
    mock_lp.assert_called_once()
    assert "Explicit_Printer" in mock_lp.call_args[0]


def test_print_pdf_returns_false_on_network_error():
    with patch("sandy.printer.requests.get", side_effect=Exception("network down")):
        success, detail = printer.print_pdf("https://example.com/puzzle.pdf")
    assert success is False
    assert "network down" in detail


def test_print_pdf_returns_false_on_lp_nonzero(tmp_path):
    mock_file = MagicMock()
    mock_file.name = str(tmp_path / "puzzle.pdf")
    with (
        patch("sandy.printer.requests.get", return_value=_mock_response()),
        patch(
            "sandy.printer._lp_print",
            return_value=(False, "lp exited 1: lp: Error - printer not found"),
        ),
        patch("sandy.printer.tempfile.NamedTemporaryFile") as mock_tmp,
        patch("sandy.printer.os.unlink"),
        patch("sandy.printer.os.path.exists", return_value=False),
    ):
        mock_tmp.return_value.__enter__.return_value = mock_file
        success, detail = printer.print_pdf("https://example.com/puzzle.pdf")
    assert success is False
    assert "lp: Error - printer not found" in detail
