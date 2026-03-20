"""Tests for sandy/plugins/dispatch.py."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

import sandy.plugins.dispatch as dispatch_plugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def dispatch_dir(tmp_path, monkeypatch):
    """Redirect plugin to a temp dispatch dir."""
    monkeypatch.setenv("DISPATCH_OBSIDIAN_DIR", str(tmp_path))
    monkeypatch.setenv("DISPATCH_METAFRAMEWORK_DIR", str(tmp_path))
    return tmp_path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content))


# ---------------------------------------------------------------------------
# Module attributes
# ---------------------------------------------------------------------------


def test_name():
    assert dispatch_plugin.name == "dispatch"


def test_commands_include_all_three():
    cmds = dispatch_plugin.commands
    assert "dispatch status" in cmds
    assert "dispatch check" in cmds
    assert "dispatch inbox" in cmds
    # short aliases
    assert "status" in cmds
    assert "check" in cmds
    assert "inbox" in cmds


# ---------------------------------------------------------------------------
# _cmd_status
# ---------------------------------------------------------------------------


def test_status_returns_current_status_section(dispatch_dir):
    _write(
        dispatch_dir / "memory.md",
        """\
        # Dispatch Memory

        ## Some Earlier Section

        - old entry

        ## Current Status

        - **IN-PROGRESS**: Sandy — 5 open issues
        - **COMPLETE**: online-reselling

        ## Context

        - some context
        """,
    )
    result = dispatch_plugin._cmd_status()
    assert result["title"] == "Dispatch Status"
    assert "Sandy" in result["text"]
    assert "IN-PROGRESS" in result["text"]
    # Should NOT include the ## Context section
    assert "some context" not in result["text"]


def test_status_falls_back_to_first_lines_when_no_section(dispatch_dir):
    _write(
        dispatch_dir / "memory.md",
        "Line one\nLine two\nLine three\n",
    )
    result = dispatch_plugin._cmd_status()
    assert "Line one" in result["text"]


def test_status_missing_file(dispatch_dir):
    result = dispatch_plugin._cmd_status()
    assert "not found" in result["text"].lower()


# ---------------------------------------------------------------------------
# _cmd_check
# ---------------------------------------------------------------------------


def test_check_shows_log_files(dispatch_dir):
    logs_dir = dispatch_dir / "logs"
    logs_dir.mkdir()
    (logs_dir / "wake-2026-03-20_10-00-00.log").write_text("log1")
    (logs_dir / "wake-2026-03-20_11-00-00.log").write_text("log2")

    result = dispatch_plugin._cmd_check()
    assert "Recent runs" in result["text"]
    assert "wake-2026-03-20" in result["text"]


def test_check_notes_no_logs_when_dir_missing(dispatch_dir):
    result = dispatch_plugin._cmd_check()
    assert "not found" in result["text"].lower() or "No log files" in result["text"]


def test_check_shows_latest_journal(dispatch_dir):
    journal_dir = dispatch_dir / "Journal"
    journal_dir.mkdir()
    (journal_dir / "2026-03-20 day shift.md").write_text("journal content")

    result = dispatch_plugin._cmd_check()
    assert "2026-03-20 day shift" in result["text"]


def test_check_title():
    result = dispatch_plugin._cmd_check()
    assert result.get("title") == "Dispatch Activity"


# ---------------------------------------------------------------------------
# _cmd_inbox
# ---------------------------------------------------------------------------


def test_inbox_shows_contents(dispatch_dir):
    _write(
        dispatch_dir / "PM Inbox.md",
        """\
        # PM Inbox

        - [skill-request 2026-03-20]: Something useful
        """,
    )
    result = dispatch_plugin._cmd_inbox()
    assert result["title"] == "PM Inbox"
    assert "skill-request" in result["text"]


def test_inbox_empty(dispatch_dir):
    _write(dispatch_dir / "PM Inbox.md", "")
    result = dispatch_plugin._cmd_inbox()
    assert "empty" in result["text"].lower()


def test_inbox_missing_file(dispatch_dir):
    result = dispatch_plugin._cmd_inbox()
    assert "not found" in result["text"].lower()


# ---------------------------------------------------------------------------
# handle
# ---------------------------------------------------------------------------


def test_handle_status(dispatch_dir, monkeypatch):
    monkeypatch.setattr(dispatch_plugin, "_cmd_status", lambda: {"text": "status result"})
    assert dispatch_plugin.handle("status", "tom") == {"text": "status result"}


def test_handle_dispatch_status(dispatch_dir, monkeypatch):
    monkeypatch.setattr(dispatch_plugin, "_cmd_status", lambda: {"text": "status result"})
    assert dispatch_plugin.handle("dispatch status", "tom") == {"text": "status result"}


def test_handle_check(dispatch_dir, monkeypatch):
    monkeypatch.setattr(dispatch_plugin, "_cmd_check", lambda: {"text": "check result"})
    assert dispatch_plugin.handle("check", "tom") == {"text": "check result"}


def test_handle_inbox(dispatch_dir, monkeypatch):
    monkeypatch.setattr(dispatch_plugin, "_cmd_inbox", lambda: {"text": "inbox result"})
    assert dispatch_plugin.handle("inbox", "tom") == {"text": "inbox result"}


def test_handle_unknown_command():
    result = dispatch_plugin.handle("dispatch frobnicate", "tom")
    assert "Unknown" in result["text"]


def test_handle_case_insensitive(monkeypatch):
    monkeypatch.setattr(dispatch_plugin, "_cmd_status", lambda: {"text": "ok"})
    assert dispatch_plugin.handle("STATUS", "tom") == {"text": "ok"}
    assert dispatch_plugin.handle("Dispatch Status", "tom") == {"text": "ok"}
