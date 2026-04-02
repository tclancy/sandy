"""Tests for sandy/plugins/estimatedtaxes.py."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import sandy.plugins.estimatedtaxes as tax_plugin


# ---------------------------------------------------------------------------
# Module attributes
# ---------------------------------------------------------------------------


def test_name():
    assert tax_plugin.name == "estimatedtaxes"


def test_commands():
    assert "tax summary" in tax_plugin.commands
    assert "tax list" in tax_plugin.commands


# ---------------------------------------------------------------------------
# _available
# ---------------------------------------------------------------------------


def test_available_true(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: "/home/tom/.local/bin/estimatedtaxes")
    assert tax_plugin._available() is True


def test_available_false(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    assert tax_plugin._available() is False


# ---------------------------------------------------------------------------
# _run — not installed
# ---------------------------------------------------------------------------


def test_run_not_available(monkeypatch):
    monkeypatch.setattr(tax_plugin, "_available", lambda: False)
    result = tax_plugin._run("summarize")
    assert result["title"] == "Taxes"
    assert "not available" in result["text"].lower()


# ---------------------------------------------------------------------------
# _run — subprocess outcomes
# ---------------------------------------------------------------------------


def _mock_run(stdout="", stderr="", returncode=0):
    mock = MagicMock()
    mock.stdout = stdout
    mock.stderr = stderr
    mock.returncode = returncode
    return mock


def test_run_success(monkeypatch):
    monkeypatch.setattr(tax_plugin, "_available", lambda: True)
    summary = "2026 summary: $12,000 income, $3,000 estimated tax"
    with patch("subprocess.run", return_value=_mock_run(stdout=summary)):
        result = tax_plugin._run("summarize")
    assert result["title"] == "Taxes"
    assert "12,000" in result["text"]


def test_run_failure_shows_stderr(monkeypatch):
    monkeypatch.setattr(tax_plugin, "_available", lambda: True)
    with patch("subprocess.run", return_value=_mock_run(stderr="database error", returncode=1)):
        result = tax_plugin._run("summarize")
    assert "Error" in result["text"]
    assert "database error" in result["text"]


def test_run_failure_no_stderr(monkeypatch):
    monkeypatch.setattr(tax_plugin, "_available", lambda: True)
    with patch("subprocess.run", return_value=_mock_run(returncode=2)):
        result = tax_plugin._run("list")
    assert "code 2" in result["text"]


def test_run_timeout(monkeypatch):
    monkeypatch.setattr(tax_plugin, "_available", lambda: True)
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="estimatedtaxes", timeout=30),
    ):
        result = tax_plugin._run("summarize")
    assert "timed out" in result["text"].lower()


def test_run_empty_output(monkeypatch):
    monkeypatch.setattr(tax_plugin, "_available", lambda: True)
    with patch("subprocess.run", return_value=_mock_run(stdout="")):
        result = tax_plugin._run("list")
    assert result["text"] == "(no output)"


# ---------------------------------------------------------------------------
# handle — routing
# ---------------------------------------------------------------------------


def test_handle_tax_summary(monkeypatch):
    monkeypatch.setattr(
        tax_plugin, "_run", lambda *args: {"title": "Taxes", "text": " ".join(args)}
    )
    result = tax_plugin.handle("tax summary", "tom")
    assert result["text"] == "summarize"


def test_handle_tax_summary_case_insensitive(monkeypatch):
    monkeypatch.setattr(
        tax_plugin, "_run", lambda *args: {"title": "Taxes", "text": " ".join(args)}
    )
    result = tax_plugin.handle("TAX SUMMARY", "tom")
    assert result["text"] == "summarize"


def test_handle_tax_list(monkeypatch):
    monkeypatch.setattr(
        tax_plugin, "_run", lambda *args: {"title": "Taxes", "text": " ".join(args)}
    )
    result = tax_plugin.handle("tax list", "tom")
    assert result["text"] == "list"


def test_handle_unknown():
    result = tax_plugin.handle("tax file return", "tom")
    assert "Unknown" in result["text"]


# ---------------------------------------------------------------------------
# No write operations exposed
# ---------------------------------------------------------------------------


def test_no_enter_command():
    """Verify 'enter' is not in commands — write ops stay CLI-only."""
    for cmd in tax_plugin.commands:
        assert "enter" not in cmd
        assert "add" not in cmd
        assert "record" not in cmd


# ---------------------------------------------------------------------------
# Integration with matcher
# ---------------------------------------------------------------------------


def test_commands_match_via_substring():
    from sandy.matcher import find_matches

    class FakePlugin:
        commands = tax_plugin.commands

    plugins = [FakePlugin()]

    assert find_matches("tax summary", plugins)
    assert find_matches("tax list", plugins)
    assert not find_matches("tax enter 1000", plugins)
