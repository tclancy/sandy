"""Tests for sandy.printer — shared PDF printing utility."""

from unittest.mock import patch, MagicMock

from sandy import printer
from sandy.printer import _is_ipp_uri, _build_lp_command


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


def _mock_run_failure(stderr="lpr: Error - printer not found", returncode=1):
    mock = MagicMock()
    mock.returncode = returncode
    mock.stderr = stderr
    mock.stdout = ""
    return mock


# ---------------------------------------------------------------------------
# _is_ipp_uri
# ---------------------------------------------------------------------------


def test_is_ipp_uri_plain_name():
    assert _is_ipp_uri("Brother_MFC_L2750DW_series") is False


def test_is_ipp_uri_ipp_scheme():
    assert _is_ipp_uri("ipp://192.168.1.50/ipp/print") is True


def test_is_ipp_uri_ipps_scheme():
    assert _is_ipp_uri("ipps://192.168.1.50/ipp/print") is True


# ---------------------------------------------------------------------------
# _build_lp_command
# ---------------------------------------------------------------------------


def test_build_lp_command_named_printer():
    cmd = _build_lp_command("MyPrinter", "/tmp/file.pdf")
    assert cmd == ["lpr", "-P", "MyPrinter", "/tmp/file.pdf"]


def test_build_lp_command_ipp_uri():
    cmd = _build_lp_command("ipp://192.168.1.50/ipp/print", "/tmp/file.pdf")
    assert cmd == ["lp", "-d", "ipp://192.168.1.50/ipp/print", "/tmp/file.pdf"]


# ---------------------------------------------------------------------------
# print_pdf — success paths
# ---------------------------------------------------------------------------


def test_print_pdf_returns_true_on_success(tmp_path):
    mock_file = MagicMock()
    mock_file.name = str(tmp_path / "puzzle.pdf")
    with (
        patch("sandy.printer.requests.get", return_value=_mock_response()),
        patch("sandy.printer.subprocess.run", return_value=_mock_run_success()),
        patch("sandy.printer.tempfile.NamedTemporaryFile") as mock_tmp,
        patch("sandy.printer.os.unlink"),
        patch("sandy.printer.os.path.exists", return_value=False),
    ):
        mock_tmp.return_value.__enter__.return_value = mock_file
        success, detail = printer.print_pdf("https://example.com/puzzle.pdf")
    assert success is True
    assert detail == ""


def test_print_pdf_calls_lpr(tmp_path):
    mock_file = MagicMock()
    mock_file.name = str(tmp_path / "puzzle.pdf")
    with (
        patch("sandy.printer.requests.get", return_value=_mock_response()),
        patch("sandy.printer.subprocess.run", return_value=_mock_run_success()) as mock_run,
        patch("sandy.printer.tempfile.NamedTemporaryFile") as mock_tmp,
        patch("sandy.printer.os.unlink"),
        patch("sandy.printer.os.path.exists", return_value=False),
    ):
        mock_tmp.return_value.__enter__.return_value = mock_file
        printer.print_pdf("https://example.com/puzzle.pdf")
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "lpr"
    assert "-P" in args


def test_print_pdf_uses_sandy_printer_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDY_PRINTER", "My_Custom_Printer")
    mock_file = MagicMock()
    mock_file.name = str(tmp_path / "puzzle.pdf")
    with (
        patch("sandy.printer.requests.get", return_value=_mock_response()),
        patch("sandy.printer.subprocess.run", return_value=_mock_run_success()) as mock_run,
        patch("sandy.printer.tempfile.NamedTemporaryFile") as mock_tmp,
        patch("sandy.printer.os.unlink"),
        patch("sandy.printer.os.path.exists", return_value=False),
    ):
        mock_tmp.return_value.__enter__.return_value = mock_file
        printer.print_pdf("https://example.com/puzzle.pdf")
    args = mock_run.call_args[0][0]
    assert "My_Custom_Printer" in args


def test_print_pdf_accepts_explicit_printer(tmp_path):
    mock_file = MagicMock()
    mock_file.name = str(tmp_path / "puzzle.pdf")
    with (
        patch("sandy.printer.requests.get", return_value=_mock_response()),
        patch("sandy.printer.subprocess.run", return_value=_mock_run_success()) as mock_run,
        patch("sandy.printer.tempfile.NamedTemporaryFile") as mock_tmp,
        patch("sandy.printer.os.unlink"),
        patch("sandy.printer.os.path.exists", return_value=False),
    ):
        mock_tmp.return_value.__enter__.return_value = mock_file
        printer.print_pdf("https://example.com/puzzle.pdf", printer="Explicit_Printer")
    args = mock_run.call_args[0][0]
    assert "Explicit_Printer" in args


# ---------------------------------------------------------------------------
# print_pdf — IPP URI path
# ---------------------------------------------------------------------------


def test_print_pdf_ipp_uri_uses_lp(tmp_path):
    mock_file = MagicMock()
    mock_file.name = str(tmp_path / "puzzle.pdf")
    with (
        patch("sandy.printer.requests.get", return_value=_mock_response()),
        patch("sandy.printer.subprocess.run", return_value=_mock_run_success()) as mock_run,
        patch("sandy.printer.tempfile.NamedTemporaryFile") as mock_tmp,
        patch("sandy.printer.os.unlink"),
        patch("sandy.printer.os.path.exists", return_value=False),
    ):
        mock_tmp.return_value.__enter__.return_value = mock_file
        success, _ = printer.print_pdf(
            "https://example.com/puzzle.pdf", printer="ipp://192.168.1.50/ipp/print"
        )
    assert success is True
    args = mock_run.call_args[0][0]
    assert args[0] == "lp"
    assert "-d" in args
    assert "ipp://192.168.1.50/ipp/print" in args


# ---------------------------------------------------------------------------
# print_pdf — failure paths
# ---------------------------------------------------------------------------


def test_print_pdf_returns_false_on_network_error():
    with patch("sandy.printer.requests.get", side_effect=Exception("network down")):
        success, detail = printer.print_pdf("https://example.com/puzzle.pdf")
    assert success is False
    assert "network down" in detail


def test_print_pdf_returns_false_on_lpr_nonzero(tmp_path):
    mock_file = MagicMock()
    mock_file.name = str(tmp_path / "puzzle.pdf")
    with (
        patch("sandy.printer.requests.get", return_value=_mock_response()),
        patch(
            "sandy.printer.subprocess.run",
            return_value=_mock_run_failure("lpr: Error - printer not found"),
        ),
        patch("sandy.printer.tempfile.NamedTemporaryFile") as mock_tmp,
        patch("sandy.printer.os.unlink"),
        patch("sandy.printer.os.path.exists", return_value=False),
        patch("sandy.printer._list_cups_printers", return_value=None),
    ):
        mock_tmp.return_value.__enter__.return_value = mock_file
        success, detail = printer.print_pdf("https://example.com/puzzle.pdf")
    assert success is False
    assert "lpr: Error - printer not found" in detail


def test_print_pdf_detail_includes_cups_printers_on_failure(tmp_path):
    mock_file = MagicMock()
    mock_file.name = str(tmp_path / "puzzle.pdf")
    with (
        patch("sandy.printer.requests.get", return_value=_mock_response()),
        patch(
            "sandy.printer.subprocess.run",
            return_value=_mock_run_failure("printer unknown"),
        ),
        patch("sandy.printer.tempfile.NamedTemporaryFile") as mock_tmp,
        patch("sandy.printer.os.unlink"),
        patch("sandy.printer.os.path.exists", return_value=False),
        patch("sandy.printer._list_cups_printers", return_value="Brother_MFC_L2750DW"),
    ):
        mock_tmp.return_value.__enter__.return_value = mock_file
        success, detail = printer.print_pdf("https://example.com/puzzle.pdf")
    assert success is False
    assert "Brother_MFC_L2750DW" in detail
