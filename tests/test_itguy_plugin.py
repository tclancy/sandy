"""Tests for sandy/plugins/itguy.py."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch


import sandy.plugins.itguy as itguy_plugin


# ---------------------------------------------------------------------------
# Module attributes
# ---------------------------------------------------------------------------


def test_name():
    assert itguy_plugin.name == "itguy"


def test_commands():
    cmds = itguy_plugin.commands
    assert "itguy list" in cmds
    assert "itguy deploy" in cmds
    assert "itguy force" in cmds


# ---------------------------------------------------------------------------
# _available
# ---------------------------------------------------------------------------


def test_available_true(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/itguy")
    assert itguy_plugin._available() is True


def test_available_false(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    assert itguy_plugin._available() is False


# ---------------------------------------------------------------------------
# _run — itguy not installed
# ---------------------------------------------------------------------------


def test_run_not_available(monkeypatch):
    monkeypatch.setattr(itguy_plugin, "_available", lambda: False)
    result = itguy_plugin._run("list")
    assert result["title"] == "IT Guy"
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
    monkeypatch.setattr(itguy_plugin, "_available", lambda: True)
    with patch("subprocess.run", return_value=_mock_run(stdout="sandy  git-build")):
        result = itguy_plugin._run("list")
    assert result["title"] == "IT Guy"
    assert "sandy" in result["text"]


def test_run_failure_shows_stderr(monkeypatch):
    monkeypatch.setattr(itguy_plugin, "_available", lambda: True)
    with patch(
        "subprocess.run", return_value=_mock_run(stderr="unknown service 'oops'", returncode=1)
    ):
        result = itguy_plugin._run("deploy", "oops")
    assert "Error" in result["text"]
    assert "oops" in result["text"]


def test_run_failure_no_stderr(monkeypatch):
    monkeypatch.setattr(itguy_plugin, "_available", lambda: True)
    with patch("subprocess.run", return_value=_mock_run(returncode=2)):
        result = itguy_plugin._run("deploy", "broken")
    assert "code 2" in result["text"]


def test_run_timeout(monkeypatch):
    monkeypatch.setattr(itguy_plugin, "_available", lambda: True)
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="itguy", timeout=120)):
        result = itguy_plugin._run("deploy", "sandy")
    assert "timed out" in result["text"].lower()


def test_run_empty_output(monkeypatch):
    monkeypatch.setattr(itguy_plugin, "_available", lambda: True)
    with patch("subprocess.run", return_value=_mock_run(stdout="")):
        result = itguy_plugin._run("list")
    assert result["text"] == "(no output)"


# ---------------------------------------------------------------------------
# handle — routing
# ---------------------------------------------------------------------------


def test_handle_list(monkeypatch):
    monkeypatch.setattr(
        itguy_plugin, "_run", lambda *args: {"title": "IT Guy", "text": " ".join(args)}
    )
    result = itguy_plugin.handle("itguy list", "tom")
    assert result["text"] == "list"


def test_handle_list_case_insensitive(monkeypatch):
    monkeypatch.setattr(
        itguy_plugin, "_run", lambda *args: {"title": "IT Guy", "text": " ".join(args)}
    )
    result = itguy_plugin.handle("ITGUY LIST", "tom")
    assert result["text"] == "list"


def test_handle_deploy_with_service(monkeypatch):
    monkeypatch.setattr(
        itguy_plugin, "_run", lambda *args: {"title": "IT Guy", "text": " ".join(args)}
    )
    result = itguy_plugin.handle("itguy deploy sandy", "tom")
    assert result["text"] == "deploy sandy"


def test_handle_deploy_no_service():
    result = itguy_plugin.handle("itguy deploy", "tom")
    assert "Usage" in result["text"]


def test_handle_force_with_service(monkeypatch):
    monkeypatch.setattr(
        itguy_plugin, "_run", lambda *args: {"title": "IT Guy", "text": " ".join(args)}
    )
    result = itguy_plugin.handle("itguy force recordclub", "tom")
    assert result["text"] == "deploy recordclub --force"


def test_handle_force_no_service():
    result = itguy_plugin.handle("itguy force", "tom")
    assert "Usage" in result["text"]


def test_handle_unknown():
    result = itguy_plugin.handle("itguy frobnicate", "tom")
    assert "Unknown" in result["text"]


# ---------------------------------------------------------------------------
# Integration with matcher (substring match)
# ---------------------------------------------------------------------------


def test_commands_match_via_substring():
    """Verify commands work as substrings for Sandy's find_matches() logic."""
    from sandy.matcher import find_matches

    class FakePlugin:
        commands = itguy_plugin.commands

    plugins = [FakePlugin()]

    assert find_matches("itguy list", plugins)
    assert find_matches("itguy deploy sandy", plugins)
    assert find_matches("itguy force recordclub", plugins)
    assert not find_matches("weather today", plugins)
