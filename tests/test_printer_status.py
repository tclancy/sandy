"""Tests for sandy.plugins.printer_status."""

import os
from unittest.mock import MagicMock, patch

from sandy.plugins.printer_status import _printer_status, _test_ipp_connectivity, handle


def test_test_ipp_connectivity_reachable():
    mock_sock = MagicMock()
    with patch("socket.create_connection", return_value=mock_sock):
        ok, detail = _test_ipp_connectivity("ipp://192.168.1.50/ipp/print")
    assert ok is True
    assert "192.168.1.50:631" in detail
    mock_sock.close.assert_called_once()


def test_test_ipp_connectivity_unreachable():
    with patch("socket.create_connection", side_effect=OSError("Connection refused")):
        ok, detail = _test_ipp_connectivity("ipp://192.168.1.50/ipp/print")
    assert ok is False
    assert "Connection refused" in detail


def test_test_ipp_connectivity_custom_port():
    mock_sock = MagicMock()
    with patch("socket.create_connection", return_value=mock_sock) as mock_connect:
        ok, _ = _test_ipp_connectivity("ipp://printer.local:9631/ipp/print")
    assert ok is True
    mock_connect.assert_called_once_with(("printer.local", 9631), timeout=5)


def test_handle_printer_status_routes():
    with (
        patch("sandy.plugins.printer_status._printer_status") as mock_status,
    ):
        mock_status.return_value = {"title": "Printer Status", "text": "ok"}
        result = handle("printer status", "tom")
    mock_status.assert_called_once()
    assert result["title"] == "Printer Status"


def test_handle_unknown_command():
    result = handle("printer foo", "tom")
    assert "Unknown printer command" in result["text"]


def test_printer_status_ipp_reachable():
    with (
        patch.dict(os.environ, {"SANDY_PRINTER": "ipp://192.168.1.50/ipp/print"}),
        patch(
            "sandy.plugins.printer_status._test_ipp_connectivity",
            return_value=(True, "192.168.1.50:631 reachable"),
        ),
    ):
        result = _printer_status()
    assert "ipp://192.168.1.50/ipp/print" in result["text"]
    assert "IPP direct" in result["text"]
    assert "reachable" in result["text"]


def test_printer_status_ipp_unreachable():
    with (
        patch.dict(os.environ, {"SANDY_PRINTER": "ipp://192.168.1.50/ipp/print"}),
        patch(
            "sandy.plugins.printer_status._test_ipp_connectivity",
            return_value=(False, "Connection refused"),
        ),
    ):
        result = _printer_status()
    assert "Connection refused" in result["text"]
    assert "✗" in result["text"]


def test_printer_status_cups_with_printers():
    with (
        patch.dict(os.environ, {"SANDY_PRINTER": "Brother_MFC"}, clear=False),
        patch("sandy.plugins.printer_status._list_cups_printers", return_value="Brother_MFC"),
        patch("sandy.plugins.printer_status._discover_ipp_uris", return_value=[]),
    ):
        result = _printer_status()
    assert "CUPS queue name" in result["text"]
    assert "Brother_MFC" in result["text"]


def test_printer_status_cups_with_discovered_ipp():
    with (
        patch.dict(os.environ, {"SANDY_PRINTER": "Brother_MFC"}, clear=False),
        patch("sandy.plugins.printer_status._list_cups_printers", return_value=None),
        patch(
            "sandy.plugins.printer_status._discover_ipp_uris",
            return_value=["ipp://192.168.1.50/ipp/print"],
        ),
    ):
        result = _printer_status()
    assert "ipp://192.168.1.50/ipp/print" in result["text"]
    assert "Set one of these" in result["text"]


def test_printer_status_default_printer_no_cups():
    # Default printer, no CUPS printers, no discovery
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("sandy.plugins.printer_status._list_cups_printers", return_value=None),
        patch("sandy.plugins.printer_status._discover_ipp_uris", return_value=[]),
    ):
        # Remove SANDY_PRINTER if set
        os.environ.pop("SANDY_PRINTER", None)
        result = _printer_status()
    assert "Brother_MFC_L2750DW_series" in result["text"]
    assert "CUPS queue name" in result["text"]
