"""Tests for sandy.printer — shared PDF printing utility."""

from unittest.mock import patch, MagicMock

from sandy import printer


def _mock_successful_print(tmp_path, printer_name="Brother_MFC_L2750DW_series"):
    """Patch all I/O in print_pdf; return a list of context managers."""
    pdf_content = b"%PDF fake content"
    mock_response = MagicMock(content=pdf_content)
    mock_file = MagicMock()
    mock_file.name = str(tmp_path / "puzzle.pdf")
    return [
        patch("sandy.printer.requests.get", return_value=mock_response),
        patch("sandy.printer.subprocess.run"),
        patch("sandy.printer.tempfile.NamedTemporaryFile"),
        patch("sandy.printer.os.unlink"),
        patch("sandy.printer.os.path.exists", return_value=False),
    ], mock_file


def test_print_pdf_returns_true_on_success(tmp_path):
    patches, mock_file = _mock_successful_print(tmp_path)
    with patches[0], patches[1], patches[2] as mock_tmp, patches[3], patches[4]:
        mock_tmp.return_value.__enter__.return_value = mock_file
        result = printer.print_pdf("https://example.com/puzzle.pdf")
    assert result is True


def test_print_pdf_calls_lpr(tmp_path):
    patches, mock_file = _mock_successful_print(tmp_path)
    with patches[0], patches[1] as mock_run, patches[2] as mock_tmp, patches[3], patches[4]:
        mock_tmp.return_value.__enter__.return_value = mock_file
        printer.print_pdf("https://example.com/puzzle.pdf")
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "lpr"
    assert "-P" in args


def test_print_pdf_uses_sandy_printer_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDY_PRINTER", "My_Custom_Printer")
    patches, mock_file = _mock_successful_print(tmp_path)
    with patches[0], patches[1] as mock_run, patches[2] as mock_tmp, patches[3], patches[4]:
        mock_tmp.return_value.__enter__.return_value = mock_file
        printer.print_pdf("https://example.com/puzzle.pdf")
    args = mock_run.call_args[0][0]
    assert "My_Custom_Printer" in args


def test_print_pdf_accepts_explicit_printer(tmp_path):
    patches, mock_file = _mock_successful_print(tmp_path)
    with patches[0], patches[1] as mock_run, patches[2] as mock_tmp, patches[3], patches[4]:
        mock_tmp.return_value.__enter__.return_value = mock_file
        printer.print_pdf("https://example.com/puzzle.pdf", printer="Explicit_Printer")
    args = mock_run.call_args[0][0]
    assert "Explicit_Printer" in args


def test_print_pdf_returns_false_on_network_error():
    with patch("sandy.printer.requests.get", side_effect=Exception("network down")):
        result = printer.print_pdf("https://example.com/puzzle.pdf")
    assert result is False


def test_print_pdf_returns_false_on_lpr_error(tmp_path):
    patches, mock_file = _mock_successful_print(tmp_path)
    with (
        patches[0],
        patch("sandy.printer.subprocess.run", side_effect=Exception("lpr not found")),
        patches[2] as mock_tmp,
        patches[3],
        patches[4],
    ):
        mock_tmp.return_value.__enter__.return_value = mock_file
        result = printer.print_pdf("https://example.com/puzzle.pdf")
    assert result is False
