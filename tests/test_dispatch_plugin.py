"""Tests for sandy/plugins/dispatch.py."""

from __future__ import annotations

import textwrap
import urllib.error
from pathlib import Path

import pytest

import sandy.plugins.dispatch as dispatch_plugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_dispatchd_http_env(monkeypatch):
    """Ensure HTTP-backend env vars don't leak into local-file tests."""
    monkeypatch.delenv("DISPATCHD_BASE_URL", raising=False)
    monkeypatch.delenv("DISPATCHD_KEY_ID", raising=False)
    monkeypatch.delenv("DISPATCHD_SECRET", raising=False)


@pytest.fixture()
def dispatch_dir(tmp_path, monkeypatch):
    """Redirect plugin to a temp dispatch dir (simulates local Mac environment)."""
    monkeypatch.setenv("DISPATCH_OBSIDIAN_DIR", str(tmp_path))
    monkeypatch.setenv("DISPATCH_METAFRAMEWORK_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def http_backend(monkeypatch):
    """Configure the HTTP backend env vars for HMAC-signed dispatchd calls."""
    monkeypatch.setenv("DISPATCHD_BASE_URL", "http://mac.local:8787")
    monkeypatch.setenv("DISPATCHD_KEY_ID", "sandy-test")
    monkeypatch.setenv("DISPATCHD_SECRET", "s" * 64)


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
    # no shortnames — all commands require the dispatch prefix
    assert "status" not in cmds
    assert "check" not in cmds
    assert "pm" not in cmds


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


def test_handle_dispatch_status(dispatch_dir, monkeypatch):
    monkeypatch.setattr(dispatch_plugin, "_cmd_status", lambda: {"text": "status result"})
    assert dispatch_plugin.handle("dispatch status", "tom") == {"text": "status result"}


def test_handle_dispatch_check(dispatch_dir, monkeypatch):
    monkeypatch.setattr(dispatch_plugin, "_cmd_check", lambda: {"text": "check result"})
    assert dispatch_plugin.handle("dispatch check", "tom") == {"text": "check result"}


def test_handle_dispatch_pm(dispatch_dir, monkeypatch):
    monkeypatch.setattr(dispatch_plugin, "_cmd_pm", lambda: {"text": "pm result"})
    assert dispatch_plugin.handle("dispatch pm", "tom") == {"text": "pm result"}


def test_handle_shortname_status_rejected():
    result = dispatch_plugin.handle("status", "tom")
    assert "Unknown" in result["text"]


def test_handle_shortname_check_rejected():
    result = dispatch_plugin.handle("check", "tom")
    assert "Unknown" in result["text"]


def test_handle_shortname_pm_rejected():
    result = dispatch_plugin.handle("pm", "tom")
    assert "Unknown" in result["text"]


def test_handle_unknown_command():
    result = dispatch_plugin.handle("dispatch frobnicate", "tom")
    assert "Unknown" in result["text"]


def test_handle_case_insensitive(monkeypatch):
    monkeypatch.setattr(dispatch_plugin, "_cmd_status", lambda: {"text": "ok"})
    assert dispatch_plugin.handle("Dispatch Status", "tom") == {"text": "ok"}
    assert dispatch_plugin.handle("DISPATCH STATUS", "tom") == {"text": "ok"}


# ---------------------------------------------------------------------------
# HTTP backend (dispatchd, #136)
# ---------------------------------------------------------------------------


def test_http_config_returns_none_when_partial(monkeypatch):
    monkeypatch.setenv("DISPATCHD_BASE_URL", "http://mac.local:8787")
    monkeypatch.setenv("DISPATCHD_KEY_ID", "sandy-test")
    # DISPATCHD_SECRET intentionally left unset
    assert dispatch_plugin._http_config() is None


def test_http_config_returns_tuple_when_all_set(http_backend):
    cfg = dispatch_plugin._http_config()
    assert cfg == ("http://mac.local:8787", "sandy-test", "s" * 64)


def test_http_config_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("DISPATCHD_BASE_URL", "http://mac.local:8787/")
    monkeypatch.setenv("DISPATCHD_KEY_ID", "k")
    monkeypatch.setenv("DISPATCHD_SECRET", "s")
    cfg = dispatch_plugin._http_config()
    assert cfg is not None
    assert cfg[0] == "http://mac.local:8787"


def test_remote_context_false_when_http_configured(http_backend, monkeypatch, tmp_path):
    """HTTP backend overrides remote-context short-circuit."""
    nonexistent = str(tmp_path / "does_not_exist")
    monkeypatch.setenv("DISPATCH_OBSIDIAN_DIR", nonexistent)
    monkeypatch.setenv("DISPATCH_METAFRAMEWORK_DIR", nonexistent)
    assert dispatch_plugin._remote_context() is False


def _stub_call(monkeypatch, envelope: dict) -> list[str]:
    """Stub _call_dispatchd; return the list that records requested paths."""
    calls: list[str] = []

    def fake(path: str) -> dict:
        calls.append(path)
        return envelope

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", fake)
    return calls


def test_cmd_status_uses_http_when_configured(http_backend, monkeypatch):
    envelope = {
        "data": {
            "text": textwrap.dedent(
                """\
                # Memory

                ## Current Status

                - **IN-PROGRESS**: Sandy

                ## Context

                - background
                """
            ),
        },
        "as_of": "2026-07-13T01:00:00Z",
    }
    calls = _stub_call(monkeypatch, envelope)
    result = dispatch_plugin._cmd_status()
    assert calls == ["/v1/dispatch/status"]
    assert result["title"] == "Dispatch Status"
    assert "IN-PROGRESS" in result["text"]
    assert "background" not in result["text"]


def test_cmd_status_http_empty_memory(http_backend, monkeypatch):
    _stub_call(monkeypatch, {"data": {"text": ""}})
    result = dispatch_plugin._cmd_status()
    assert result["title"] == "Dispatch Status"
    assert "empty" in result["text"].lower()


def test_cmd_status_http_error(http_backend, monkeypatch):
    def raise_urlerror(_path):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", raise_urlerror)
    result = dispatch_plugin._cmd_status()
    assert "unreachable" in result["text"]


def test_cmd_pm_uses_http_when_configured(http_backend, monkeypatch):
    envelope = {
        "data": {
            "text": textwrap.dedent(
                """\
                ---
                title: PM Inbox
                ---
                # PM Inbox

                - [skill-request 2026-03-20]: something
                """
            ),
        }
    }
    _stub_call(monkeypatch, envelope)
    result = dispatch_plugin._cmd_pm()
    assert result["title"] == "PM Inbox"
    assert "skill-request" in result["text"]
    assert "title: PM Inbox" not in result["text"]  # frontmatter stripped


def test_cmd_pm_http_empty(http_backend, monkeypatch):
    _stub_call(monkeypatch, {"data": {"text": "   \n"}})
    result = dispatch_plugin._cmd_pm()
    assert "empty" in result["text"].lower()


def test_cmd_check_uses_http_when_configured(http_backend, monkeypatch):
    envelope = {
        "data": {
            "status": "ok",
            "in_flight": {
                "session_type": "dayshift",
                "pid": 12345,
                "started_at": "2026-07-13T01:00:00Z",
            },
        },
        "as_of": "2026-07-13T01:05:00Z",
    }
    calls = _stub_call(monkeypatch, envelope)
    result = dispatch_plugin._cmd_check()
    assert calls == ["/v1/health"]
    assert result["title"] == "Dispatch Activity"
    assert "Health: ok" in result["text"]
    assert "dayshift" in result["text"]
    assert "12345" in result["text"]
    assert "As of: 2026-07-13T01:05:00Z" in result["text"]


def test_cmd_check_http_no_in_flight(http_backend, monkeypatch):
    _stub_call(monkeypatch, {"data": {"status": "ok", "in_flight": None}})
    result = dispatch_plugin._cmd_check()
    assert "In-flight: none" in result["text"]


def test_cmd_check_http_error(http_backend, monkeypatch):
    class FakeHTTPError(urllib.error.HTTPError):
        def __init__(self):
            super().__init__(url="", code=401, msg="unauthorized", hdrs=None, fp=None)

    def raise_http(_path):
        raise FakeHTTPError()

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", raise_http)
    result = dispatch_plugin._cmd_check()
    assert "401" in result["text"]


def test_call_dispatchd_signs_request(http_backend, monkeypatch):
    """_call_dispatchd sends Authorization + X-Nonce + X-Timestamp with the
    HMAC-SHA256 signature computed over method / path / body-sha / nonce / ts.
    """
    import hashlib
    import hmac as hmac_mod
    import json

    captured: dict[str, dispatch_plugin.urllib.request.Request] = {}

    class FakeResp:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self) -> bytes:
            return self._payload

    def fake_urlopen(req, timeout):  # noqa: ARG001
        captured["req"] = req
        return FakeResp(json.dumps({"data": {"text": "hi"}}).encode("utf-8"))

    monkeypatch.setattr(dispatch_plugin.urllib.request, "urlopen", fake_urlopen)

    envelope = dispatch_plugin._call_dispatchd("/v1/dispatch/status")
    assert envelope == {"data": {"text": "hi"}}

    req = captured["req"]
    assert req.full_url == "http://mac.local:8787/v1/dispatch/status"
    assert req.headers["X-nonce"]  # header case-normalized by urllib
    ts = req.headers["X-timestamp"]
    auth = req.headers["Authorization"]
    key_id, sig = auth[len("HMAC ") :].split(":", 1)
    assert key_id == "sandy-test"

    body_sha = hashlib.sha256(b"").hexdigest()
    canonical = f"GET\n/v1/dispatch/status\n{body_sha}\n{req.headers['X-nonce']}\n{ts}"
    expected = hmac_mod.new(("s" * 64).encode(), canonical.encode(), hashlib.sha256).hexdigest()
    assert sig == expected
