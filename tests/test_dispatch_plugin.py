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
    """Redirect plugin to a temp dispatch dir (simulates local Mac environment)."""
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
    assert "dispatch pm" in cmds
    # short aliases
    assert "status" in cmds
    assert "check" in cmds
    assert "pm" in cmds


def test_commands_do_not_include_inbox():
    cmds = dispatch_plugin.commands
    assert "inbox" not in cmds
    assert "dispatch inbox" not in cmds


# ---------------------------------------------------------------------------
# _remote_context
# ---------------------------------------------------------------------------


def test_remote_context_true_when_dirs_missing(monkeypatch, tmp_path):
    """Returns True when neither dispatch dir nor metaframework dir exists."""
    nonexistent = str(tmp_path / "does_not_exist")
    monkeypatch.setenv("DISPATCH_OBSIDIAN_DIR", nonexistent)
    monkeypatch.setenv("DISPATCH_METAFRAMEWORK_DIR", nonexistent)
    assert dispatch_plugin._remote_context() is True


def test_remote_context_false_when_dispatch_dir_exists(dispatch_dir):
    """Returns False when the dispatch dir exists (even if metaframework dir doesn't)."""
    assert dispatch_plugin._remote_context() is False


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


def test_status_remote_context(monkeypatch, tmp_path):
    """Returns friendly message when running remotely."""
    nonexistent = str(tmp_path / "does_not_exist")
    monkeypatch.setenv("DISPATCH_OBSIDIAN_DIR", nonexistent)
    monkeypatch.setenv("DISPATCH_METAFRAMEWORK_DIR", nonexistent)
    result = dispatch_plugin._cmd_status()
    assert result["title"] == "Dispatch Status"
    assert "remotely" in result["text"].lower()


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


def test_check_remote_context(monkeypatch, tmp_path):
    """Returns friendly message when running remotely."""
    nonexistent = str(tmp_path / "does_not_exist")
    monkeypatch.setenv("DISPATCH_OBSIDIAN_DIR", nonexistent)
    monkeypatch.setenv("DISPATCH_METAFRAMEWORK_DIR", nonexistent)
    result = dispatch_plugin._cmd_check()
    assert result["title"] == "Dispatch Activity"
    assert "remotely" in result["text"].lower()


# ---------------------------------------------------------------------------
# _cmd_pm
# ---------------------------------------------------------------------------


def test_pm_shows_contents(dispatch_dir):
    _write(
        dispatch_dir / "PM Inbox.md",
        """\
        # PM Inbox

        - [skill-request 2026-03-20]: Something useful
        """,
    )
    result = dispatch_plugin._cmd_pm()
    assert result["title"] == "PM Inbox"
    assert "skill-request" in result["text"]


def test_pm_empty(dispatch_dir):
    _write(dispatch_dir / "PM Inbox.md", "")
    result = dispatch_plugin._cmd_pm()
    assert "empty" in result["text"].lower()


def test_pm_missing_file(dispatch_dir):
    result = dispatch_plugin._cmd_pm()
    assert "not found" in result["text"].lower()


def test_pm_remote_context(monkeypatch, tmp_path):
    """Returns friendly message when running remotely."""
    nonexistent = str(tmp_path / "does_not_exist")
    monkeypatch.setenv("DISPATCH_OBSIDIAN_DIR", nonexistent)
    monkeypatch.setenv("DISPATCH_METAFRAMEWORK_DIR", nonexistent)
    result = dispatch_plugin._cmd_pm()
    assert result["title"] == "PM Inbox"
    assert "remotely" in result["text"].lower()


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


def test_handle_pm(dispatch_dir, monkeypatch):
    monkeypatch.setattr(dispatch_plugin, "_cmd_pm", lambda: {"text": "pm result"})
    assert dispatch_plugin.handle("pm", "tom") == {"text": "pm result"}


def test_handle_dispatch_pm(dispatch_dir, monkeypatch):
    monkeypatch.setattr(dispatch_plugin, "_cmd_pm", lambda: {"text": "pm result"})
    assert dispatch_plugin.handle("dispatch pm", "tom") == {"text": "pm result"}


def test_handle_unknown_command():
    result = dispatch_plugin.handle("dispatch frobnicate", "tom")
    assert "Unknown" in result["text"]


def test_handle_case_insensitive(monkeypatch):
    monkeypatch.setattr(dispatch_plugin, "_cmd_status", lambda: {"text": "ok"})
    assert dispatch_plugin.handle("STATUS", "tom") == {"text": "ok"}
    assert dispatch_plugin.handle("Dispatch Status", "tom") == {"text": "ok"}
