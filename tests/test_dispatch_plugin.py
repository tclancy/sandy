"""Tests for sandy/plugins/dispatch.py."""

from __future__ import annotations

import textwrap
import urllib.error

import pytest

import sandy.plugins.dispatch as dispatch_plugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_dispatchd_http_env(monkeypatch):
    """Start every test unconfigured; opt in via the http_backend fixture."""
    monkeypatch.delenv("DISPATCHD_BASE_URL", raising=False)
    monkeypatch.delenv("DISPATCHD_KEY_ID", raising=False)
    monkeypatch.delenv("DISPATCHD_SECRET", raising=False)


@pytest.fixture()
def http_backend(monkeypatch):
    """Configure the HTTP backend env vars for HMAC-signed dispatchd calls."""
    monkeypatch.setenv("DISPATCHD_BASE_URL", "http://mac.local:8787")
    monkeypatch.setenv("DISPATCHD_KEY_ID", "sandy-test")
    monkeypatch.setenv("DISPATCHD_SECRET", "s" * 64)


def _stub_call(monkeypatch, envelope: dict) -> list[str]:
    """Stub _call_dispatchd; return the list that records requested paths."""
    calls: list[str] = []

    def fake(path: str) -> dict:
        calls.append(path)
        return envelope

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", fake)
    return calls


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
# Unconfigured backend — the only non-HTTP path left after #136 review
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "title"),
    [
        ("dispatch status", "Dispatch Status"),
        ("dispatch check", "Dispatch Activity"),
        ("dispatch pm", "PM Inbox"),
    ],
)
def test_unconfigured_returns_friendly_message(command, title):
    result = dispatch_plugin.handle(command, "tom")
    assert result["title"] == title
    assert "DISPATCHD_BASE_URL" in result["text"]
    assert "not configured" in result["text"].lower()


def test_partial_config_is_unconfigured(monkeypatch):
    monkeypatch.setenv("DISPATCHD_BASE_URL", "http://mac.local:8787")
    monkeypatch.setenv("DISPATCHD_KEY_ID", "sandy-test")
    # DISPATCHD_SECRET intentionally left unset
    result = dispatch_plugin.handle("dispatch status", "tom")
    assert "not configured" in result["text"].lower()


# ---------------------------------------------------------------------------
# _http_config
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


# ---------------------------------------------------------------------------
# dispatch status
# ---------------------------------------------------------------------------


def test_status_extracts_current_status_section(http_backend, monkeypatch):
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
    result = dispatch_plugin.handle("dispatch status", "tom")
    assert calls == ["/v1/dispatch/status"]
    assert result["title"] == "Dispatch Status"
    assert "IN-PROGRESS" in result["text"]
    assert "background" not in result["text"]


def test_status_falls_back_to_first_lines_when_no_section(http_backend, monkeypatch):
    _stub_call(monkeypatch, {"data": {"text": "Line one\nLine two\nLine three\n"}})
    result = dispatch_plugin.handle("dispatch status", "tom")
    assert "Line one" in result["text"]
    assert "first 20 lines" not in result["text"]  # short doc: no truncation marker


def test_status_fallback_marks_truncation(http_backend, monkeypatch):
    text = "\n".join(f"line {i}" for i in range(30))
    _stub_call(monkeypatch, {"data": {"text": text}})
    result = dispatch_plugin.handle("dispatch status", "tom")
    assert "line 19" in result["text"]
    assert "line 20" not in result["text"]
    assert "first 20 lines" in result["text"]  # truncation is visible, not silent


def test_status_empty_memory(http_backend, monkeypatch):
    _stub_call(monkeypatch, {"data": {"text": ""}})
    result = dispatch_plugin.handle("dispatch status", "tom")
    assert result["title"] == "Dispatch Status"
    assert "empty" in result["text"].lower()


# ---------------------------------------------------------------------------
# dispatch check
# ---------------------------------------------------------------------------


def test_check_reports_health_and_in_flight(http_backend, monkeypatch):
    # in_flight mirrors dispatchd's Run.as_dict() (metaframework registry.py)
    envelope = {
        "data": {
            "status": "ok",
            "in_flight": {
                "run_id": "r1",
                "shift": "dayshift",
                "status": "running",
                "pid": 12345,
                "started_at": "2026-07-13T01:00:00Z",
                "ended_at": None,
                "exit_code": None,
            },
        },
        "as_of": "2026-07-13T01:05:00Z",
    }
    calls = _stub_call(monkeypatch, envelope)
    result = dispatch_plugin.handle("dispatch check", "tom")
    assert calls == ["/v1/health"]
    assert result["title"] == "Dispatch Activity"
    assert "Health: ok" in result["text"]
    assert "dayshift" in result["text"]
    assert "12345" in result["text"]
    assert "As of: 2026-07-13T01:05:00Z" in result["text"]


def test_check_no_in_flight(http_backend, monkeypatch):
    _stub_call(monkeypatch, {"data": {"status": "ok", "in_flight": None}})
    result = dispatch_plugin.handle("dispatch check", "tom")
    assert "In-flight: none" in result["text"]


# ---------------------------------------------------------------------------
# dispatch pm
# ---------------------------------------------------------------------------


def test_pm_strips_frontmatter(http_backend, monkeypatch):
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
    calls = _stub_call(monkeypatch, envelope)
    result = dispatch_plugin.handle("dispatch pm", "tom")
    assert calls == ["/v1/dispatch/pm-inbox"]
    assert result["title"] == "PM Inbox"
    assert "skill-request" in result["text"]
    assert "title: PM Inbox" not in result["text"]  # frontmatter stripped


def test_pm_empty(http_backend, monkeypatch):
    _stub_call(monkeypatch, {"data": {"text": "   \n"}})
    result = dispatch_plugin.handle("dispatch pm", "tom")
    assert "empty" in result["text"].lower()


# ---------------------------------------------------------------------------
# Error surface
# ---------------------------------------------------------------------------


def _make_http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url="", code=code, msg="nope", hdrs=None, fp=None)


def _stub_call_raises(monkeypatch, exc: Exception) -> None:
    def raise_exc(_path):
        raise exc

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", raise_exc)


def test_url_error_becomes_unreachable_message(http_backend, monkeypatch):
    _stub_call_raises(monkeypatch, urllib.error.URLError("connection refused"))
    result = dispatch_plugin.handle("dispatch status", "tom")
    assert "unreachable" in result["text"]


def test_http_error_reports_status_code(http_backend, monkeypatch):
    _stub_call_raises(monkeypatch, _make_http_error(401))
    result = dispatch_plugin.handle("dispatch check", "tom")
    assert "401" in result["text"]


def test_timeout_becomes_unreachable_message(http_backend, monkeypatch):
    """Post-connect timeouts raise bare TimeoutError, not URLError."""
    _stub_call_raises(monkeypatch, TimeoutError("timed out"))
    result = dispatch_plugin.handle("dispatch status", "tom")
    assert "unreachable" in result["text"]


def test_malformed_envelope_gets_friendly_message(http_backend, monkeypatch):
    """A 200 whose JSON isn't the envelope shape must not escape handle()."""
    captured: list = []
    monkeypatch.setattr(dispatch_plugin, "capture", lambda e, **c: captured.append(e))
    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", lambda _path: None)
    result = dispatch_plugin.handle("dispatch check", "tom")
    assert result["title"] == "Dispatch Activity"
    assert "failed" in result["text"]
    assert len(captured) == 1


def test_http_error_is_captured_to_sentry(http_backend, monkeypatch):
    captured: list[tuple] = []

    def fake_capture(error, **context):
        captured.append((error, context))

    monkeypatch.setattr(dispatch_plugin, "capture", fake_capture)
    err = _make_http_error(500)
    _stub_call_raises(monkeypatch, err)
    dispatch_plugin.handle("dispatch pm", "tom")
    assert len(captured) == 1
    assert captured[0][0] is err
    assert captured[0][1]["plugin"] == "dispatch"
    assert captured[0][1]["stage"] == "pm-inbox"


def test_unconfigured_is_not_captured_to_sentry(monkeypatch):
    """Missing config is expected control flow, not a Sentry-worthy failure."""
    captured: list = []
    monkeypatch.setattr(dispatch_plugin, "capture", lambda *a, **k: captured.append(a))
    dispatch_plugin.handle("dispatch status", "tom")
    assert captured == []


# ---------------------------------------------------------------------------
# handle routing
# ---------------------------------------------------------------------------


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


def test_handle_case_insensitive(http_backend, monkeypatch):
    _stub_call(monkeypatch, {"data": {"text": "## Current Status\nok"}})
    assert "ok" in dispatch_plugin.handle("Dispatch Status", "tom")["text"]
    assert "ok" in dispatch_plugin.handle("DISPATCH STATUS", "tom")["text"]


# ---------------------------------------------------------------------------
# HMAC signing
# ---------------------------------------------------------------------------


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

    def fake_open(req, timeout):  # noqa: ARG001
        captured["req"] = req
        return FakeResp(json.dumps({"data": {"text": "hi"}}).encode("utf-8"))

    monkeypatch.setattr(dispatch_plugin._OPENER, "open", fake_open)

    envelope = dispatch_plugin._call_dispatchd("/v1/dispatch/status")
    assert envelope == {"data": {"text": "hi"}}

    req = captured["req"]
    assert req.full_url == "http://mac.local:8787/v1/dispatch/status"
    assert req.headers["X-nonce"]  # header case-normalized by urllib
    # Cloudflare BIC bans the default Python-urllib UA (error 1010)
    assert req.headers["User-agent"] == "dispatch-sandy/1.0"
    ts = req.headers["X-timestamp"]
    auth = req.headers["Authorization"]
    key_id, sig = auth[len("HMAC ") :].split(":", 1)
    assert key_id == "sandy-test"

    body_sha = hashlib.sha256(b"").hexdigest()
    canonical = f"GET\n/v1/dispatch/status\n{body_sha}\n{req.headers['X-nonce']}\n{ts}"
    expected = hmac_mod.new(("s" * 64).encode(), canonical.encode(), hashlib.sha256).hexdigest()
    assert sig == expected


def test_opener_refuses_redirects():
    """Redirects must not be followed: urllib would forward the Authorization,
    X-Nonce, and X-Timestamp headers to the redirect target, even cross-host.
    """
    handler = next(
        h for h in dispatch_plugin._OPENER.handlers if isinstance(h, dispatch_plugin._NoRedirect)
    )
    assert handler.redirect_request(None, None, 302, "Found", {}, "http://evil.example/") is None
