"""Tests for sandy/plugins/dispatch.py."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import io
import json
import textwrap
import urllib.error

import pytest

import sandy.plugins.dispatch as dispatch_plugin
from sandy import matcher, pipeline


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


# ---------------------------------------------------------------------------
# Part C: `dispatch work <URL>` — POST /v1/dispatch/work (sandy #137)
# ---------------------------------------------------------------------------


def test_commands_include_work():
    assert "dispatch work" in dispatch_plugin.commands


@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            "dispatch work https://github.com/tclancy/sandy/issues/137",
            "https://github.com/tclancy/sandy/issues/137",
        ),
        (
            "dispatch work https://github.com/tclancy/sandy/pull/138",
            "https://github.com/tclancy/sandy/pull/138",
        ),
        # Slack wraps bare URLs in angle brackets, and uses <url|label> when a
        # display text is attached. Both must survive.
        (
            "dispatch work <https://github.com/tclancy/sandy/issues/137>",
            "https://github.com/tclancy/sandy/issues/137",
        ),
        (
            "dispatch work <https://github.com/tclancy/sandy/issues/137|sandy#137>",
            "https://github.com/tclancy/sandy/issues/137",
        ),
        # Slack's display text routinely contains spaces — it is whatever the
        # linking user typed, and GitHub's own unfurl uses the issue title. The
        # URL must be lifted out of the brackets *before* any whitespace split,
        # or the label's first space truncates the link mid-parse.
        (
            "dispatch work <https://github.com/tclancy/sandy/issues/137|sandy issue 137>",
            "https://github.com/tclancy/sandy/issues/137",
        ),
        (
            "dispatch work <https://github.com/tclancy/sandy/pull/138|Add the work client>",
            "https://github.com/tclancy/sandy/pull/138",
        ),
        # A comment permalink is the most natural thing to paste from a thread.
        (
            "dispatch work https://github.com/tclancy/sandy/issues/137#issuecomment-5041346895",
            "https://github.com/tclancy/sandy/issues/137",
        ),
        # Mixed case owner/repo, trailing slash, http, www, extra whitespace.
        (
            "  Dispatch Work   http://www.github.com/TClancy/Sandy/Issues/137/  ",
            "https://github.com/tclancy/sandy/issues/137",
        ),
    ],
)
def test_parse_work_command_accepts(raw, expected):
    assert dispatch_plugin._parse_work_command(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "dispatch work",  # no URL at all
        "dispatch work    ",
        "dispatch work https://github.com/tclancy/sandy",  # repo root, no target
        "dispatch work https://github.com/tclancy",  # org/user only
        "dispatch work https://github.com/tclancy/sandy/discussions/12",
        "dispatch work https://github.com/tclancy/sandy/blob/main/README.md",
        "dispatch work https://github.com/tclancy/sandy/tree/main",
        "dispatch work https://github.com/tclancy/sandy/wiki/Home",
        "dispatch work https://gitlab.com/tclancy/sandy/issues/137",
        "dispatch work https://github.com/tclancy/sandy/issues/notanumber",
        "dispatch work not-a-url-at-all",
    ],
)
def test_parse_work_command_rejects(raw):
    assert dispatch_plugin._parse_work_command(raw) is None


def test_parse_work_command_trusts_the_link_target_not_the_display_text():
    """Slack's display text is attacker-controlled and can claim to be one
    URL while pointing at another. Only the half before the ``|`` is the real
    destination, so a link that *reads* like a valid issue but resolves
    elsewhere must be rejected rather than parsed out of the label."""
    spoofed = (
        "dispatch work <https://evil.example.com/pwn|https://github.com/tclancy/sandy/issues/137>"
    )
    assert dispatch_plugin._parse_work_command(spoofed) is None


def test_parse_work_command_returns_none_for_other_commands():
    """The work matcher must not swallow the read commands."""
    assert dispatch_plugin._parse_work_command("dispatch status") is None
    assert dispatch_plugin._parse_work_command("dispatch check") is None


def test_work_unconfigured_returns_friendly_message():
    resp = dispatch_plugin.handle("dispatch work https://github.com/tclancy/sandy/issues/1", "tom")
    assert resp["text"] == dispatch_plugin._NOT_CONFIGURED_TEXT


def test_work_rejects_bad_url_without_calling_dispatchd(http_backend, monkeypatch):
    """Client-side shape check is belt-and-suspenders: the endpoint refuses
    these too, but a local reject is instant and does not burn a round trip."""

    def boom(*args, **kwargs):
        raise AssertionError("should not have called dispatchd")

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", boom)
    resp = dispatch_plugin.handle("dispatch work https://github.com/tclancy/sandy", "tom")
    assert "issues" in resp["text"] and "pull" in resp["text"]


def test_work_happy_path_posts_url_and_reports_target(http_backend, monkeypatch):
    captured = {}

    def fake(path, *, method="GET", payload=None):
        captured["path"] = path
        captured["method"] = method
        captured["payload"] = payload
        return {
            "data": {
                "run_id": "9f1c2b7e-0000-4000-8000-000000000001",
                "url": "https://github.com/tclancy/sandy/issues/137",
                "target": {"owner": "tclancy", "repo": "sandy", "kind": "issue", "number": 137},
                "started_at": "2026-07-27T17:42:00Z",
            }
        }

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", fake)
    resp = dispatch_plugin.handle(
        "dispatch work https://github.com/tclancy/sandy/issues/137#issuecomment-1", "tom"
    )

    assert captured["path"] == "/v1/dispatch/work"
    assert captured["method"] == "POST"
    # The canonicalized URL goes on the wire; the server re-derives the target
    # from it, so the checks run against exactly what we echoed.
    assert captured["payload"] == {"url": "https://github.com/tclancy/sandy/issues/137"}
    assert "tclancy/sandy" in resp["text"]
    assert "137" in resp["text"]
    assert "9f1c2b7e-0000-4000-8000-000000000001" in resp["text"]


def test_work_202_does_not_claim_the_run_is_running(http_backend, monkeypatch):
    """202 means *spawned*, not *running* (meta#438).

    The in-flight registry is written only by dispatchd's own endpoints, so a
    POST during a launchd-started shift passes the 409 check and then loses the
    LockManager race. Telling Tom "started" would be a lie he acts on.
    """
    monkeypatch.setattr(
        dispatch_plugin,
        "_call_dispatchd",
        lambda path, *, method="GET", payload=None: {
            "data": {
                "run_id": "r1",
                "target": {"owner": "tclancy", "repo": "sandy", "kind": "issue", "number": 137},
            }
        },
    )
    text = dispatch_plugin.handle(
        "dispatch work https://github.com/tclancy/sandy/issues/137", "tom"
    )["text"].lower()
    assert "spawned" in text
    assert "dispatch check" in text


@pytest.mark.parametrize(
    "code,error,must_mention",
    [
        (400, "bad_request", "issues"),
        (403, "forbidden", "work"),
        (403, "forbidden_owner", "owner"),
        (403, "forbidden_path", "checkout"),
        (404, "repo_not_found", "clone"),
        (409, "conflict", "in flight"),
    ],
)
def test_work_error_codes_get_actionable_messages(
    http_backend, monkeypatch, code, error, must_mention
):
    body = json.dumps({"error": error, "message": "server-side detail"}).encode()
    exc = urllib.error.HTTPError(
        "http://mac.local:8787/v1/dispatch/work", code, "err", {}, io.BytesIO(body)
    )

    def fake(path, *, method="GET", payload=None):
        raise exc

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", fake)
    resp = dispatch_plugin.handle(
        "dispatch work https://github.com/tclancy/sandy/issues/137", "tom"
    )
    assert must_mention.lower() in resp["text"].lower()


def test_work_conflict_does_not_call_itself_a_global_lock(http_backend, monkeypatch):
    """The 409 only knows about runs dispatchd itself started (meta#438).

    A scheduled shift writes no registry row, so 'nothing is in flight' is not
    the same as 'the machine is free'. The Slack copy must not overclaim.
    """
    body = json.dumps({"error": "conflict", "message": "another run is in flight"}).encode()

    def fake(path, *, method="GET", payload=None):
        raise urllib.error.HTTPError("u", 409, "conflict", {}, io.BytesIO(body))

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", fake)
    text = dispatch_plugin.handle(
        "dispatch work https://github.com/tclancy/sandy/issues/137", "tom"
    )["text"].lower()
    for overclaim in ("global", "mutex", "nothing else can run", "only one run"):
        assert overclaim not in text


def test_work_unknown_error_code_still_surfaces_the_server_message(http_backend, monkeypatch):
    body = json.dumps({"error": "teapot", "message": "I am a teapot"}).encode()

    def fake(path, *, method="GET", payload=None):
        raise urllib.error.HTTPError("u", 418, "teapot", {}, io.BytesIO(body))

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", fake)
    resp = dispatch_plugin.handle(
        "dispatch work https://github.com/tclancy/sandy/issues/137", "tom"
    )
    assert "I am a teapot" in resp["text"]


def test_work_non_json_error_body_does_not_crash(http_backend, monkeypatch):
    """A proxy or Cloudflare page in front of dispatchd returns HTML, not JSON."""

    def fake(path, *, method="GET", payload=None):
        raise urllib.error.HTTPError("u", 502, "bad gateway", {}, io.BytesIO(b"<html>nope</html>"))

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", fake)
    resp = dispatch_plugin.handle(
        "dispatch work https://github.com/tclancy/sandy/issues/137", "tom"
    )
    assert "502" in resp["text"]


def test_call_dispatchd_post_signs_the_body(http_backend, monkeypatch):
    """The HMAC canonical string hashes the request body, so a POST must sign
    the JSON payload — a GET-shaped signature over b'' would 401."""
    captured = {}

    class FakeResp:
        def __init__(self, payload: bytes):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self) -> bytes:
            return self._payload

    def fake_open(req, timeout):  # noqa: ARG001
        captured["req"] = req
        return FakeResp(json.dumps({"data": {"run_id": "r1"}}).encode("utf-8"))

    monkeypatch.setattr(dispatch_plugin._OPENER, "open", fake_open)

    payload = {"url": "https://github.com/tclancy/sandy/issues/137"}
    dispatch_plugin._call_dispatchd("/v1/dispatch/work", method="POST", payload=payload)

    req = captured["req"]
    assert req.get_method() == "POST"
    assert req.headers["Content-type"] == "application/json"
    body = req.data
    assert json.loads(body.decode()) == payload

    ts = req.headers["X-timestamp"]
    nonce = req.headers["X-nonce"]
    sig = req.headers["Authorization"][len("HMAC ") :].split(":", 1)[1]
    body_sha = hashlib.sha256(body).hexdigest()
    canonical = f"POST\n/v1/dispatch/work\n{body_sha}\n{nonce}\n{ts}"
    expected = hmac_mod.new(("s" * 64).encode(), canonical.encode(), hashlib.sha256).hexdigest()
    assert sig == expected


# ---------------------------------------------------------------------------
# Routing guard: the URL has to survive the trip from Slack to the parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "dispatch work https://github.com/tclancy/sandy/issues/137",
        "dispatch work <https://github.com/tclancy/sandy/issues/137>",
        "dispatch work <https://github.com/tclancy/sandy/issues/137|sandy#137>",
    ],
)
def test_matcher_routes_work_messages_to_this_plugin(message):
    """``matcher.normalize`` strips punctuation before matching, which turns a
    URL into an unrecognisable run of letters. That is fine — "dispatch work"
    still survives as a substring — but only as long as the *raw* text is what
    reaches handle(). This guards the routing half of that."""
    assert dispatch_plugin in matcher.find_matches(message, [dispatch_plugin])


def test_pipeline_hands_the_plugin_the_raw_url_not_the_normalized_text(http_backend, monkeypatch):
    """End-to-end through the real pipeline, because every unit test above
    calls ``handle`` directly and so cannot see this failure mode.

    ``matcher.normalize`` strips ``:`` and ``/``, which would reduce the URL to
    an unparseable run of letters. Matching uses the normalized text (fine —
    "dispatch work" survives as a substring) but ``handle`` must receive the
    raw message. If that ever flips, `dispatch work` breaks silently in Slack
    while the unit tests stay green.
    """
    captured = {}

    def fake(path, *, method="GET", payload=None):
        captured["payload"] = payload
        return {
            "data": {
                "run_id": "r1",
                "target": {"owner": "tclancy", "repo": "sandy", "kind": "issue", "number": 137},
            }
        }

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", fake)
    results, errors = pipeline.run_pipeline(
        "dispatch work <https://github.com/tclancy/sandy/issues/137|sandy#137>",
        actor="tom",
        config={},
        plugins=[dispatch_plugin],
    )

    assert errors == []
    assert [name for name, _ in results] == ["dispatch"]
    assert captured["payload"] == {"url": "https://github.com/tclancy/sandy/issues/137"}
    # The premise: normalization really would have destroyed the URL.
    assert matcher.normalize("dispatch work https://github.com/tclancy/sandy/issues/137") == (
        "dispatch work httpsgithubcomtclancysandyissues137"
    )


def test_help_documents_the_work_argument():
    """`dispatch work` alone is unusable, so help must name the argument. The
    `command_groups` hoist (itguy#131) is what keeps it off the leaf row."""
    group = dispatch_plugin.command_groups["dispatch work"]
    assert group == ["dispatch work <github issue or PR URL>"]
    # The group key is de-duped out of the flat row by help.py, so the bare
    # "dispatch work" must stay in `commands` for the matcher to route on it.
    assert "dispatch work" in dispatch_plugin.commands


# ---------------------------------------------------------------------------
# Part A: `dispatch shift <kind>` — POST /v1/dispatch/shift (sandy #137)
# ---------------------------------------------------------------------------


def _stub_post(monkeypatch, envelope: dict) -> list[dict]:
    """Stub _call_dispatchd for a POST; return the list recording each call."""
    calls: list[dict] = []

    def fake(path, *, method="GET", payload=None):
        calls.append({"path": path, "method": method, "payload": payload})
        return envelope

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", fake)
    return calls


def _shift_envelope(kind: str = "night") -> dict:
    return {
        "data": {
            "run_id": "3f2b1c00-0000-4000-8000-000000000001",
            "kind": kind,
            "slot": None,
            "started_at": "2026-07-28T07:12:00Z",
        }
    }


def test_commands_include_shift():
    assert "dispatch shift" in dispatch_plugin.commands


def test_command_groups_document_shift():
    group = dispatch_plugin.command_groups["dispatch shift"]
    assert len(group) == 1
    # Every kind dispatchd accepts should be discoverable from the help row.
    for kind in ("night", "day", "wrapup", "pmreview", "sanity", "selffix"):
        assert kind in group[0]
    # The bare phrase must stay in `commands` or the matcher never routes to us.
    assert "dispatch shift" in dispatch_plugin.commands


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("dispatch shift night", "night"),
        ("dispatch shift day", "day"),
        ("dispatch shift wrapup", "wrapup"),
        ("dispatch shift pmreview", "pmreview"),
        ("dispatch shift sanity", "sanity"),
        ("dispatch shift selffix", "selffix"),
        # Slack is a chat box: case, padding, trailing punctuation and polite
        # framing all arrive verbatim because `handle` gets the raw text.
        ("Dispatch Shift Night", "night"),
        ("  dispatch   shift   day  ", "day"),
        ("dispatch shift day.", "day"),
        ("dispatch shift day please", "day"),
        ("please dispatch shift night", "night"),
    ],
)
def test_parse_shift_command_reads_the_kind(raw, expected):
    assert dispatch_plugin._parse_shift_command(raw).kind == expected


def test_parse_shift_command_without_a_kind_offers_help():
    parsed = dispatch_plugin._parse_shift_command("dispatch shift")
    assert parsed.kind is None
    # The help must name the kinds — it is the only place they are listed.
    for kind in ("night", "day", "wrapup", "pmreview", "sanity", "selffix"):
        assert kind in parsed.error


def test_parse_shift_command_refuses_a_second_word():
    """A slot is not silently dropped — see test_shift_never_sends_a_slot for why
    sending one would be actively harmful."""
    parsed = dispatch_plugin._parse_shift_command("dispatch shift day 9am")
    assert parsed.kind is None
    assert "9am" in parsed.error


def test_shift_unconfigured_returns_friendly_message():
    resp = dispatch_plugin.handle("dispatch shift night", "tom")
    assert resp["title"] == "Dispatch Shift"
    assert "not configured" in resp["text"].lower()


def test_shift_posts_the_kind_to_the_shift_endpoint(http_backend, monkeypatch):
    calls = _stub_post(monkeypatch, _shift_envelope("night"))
    resp = dispatch_plugin.handle("dispatch shift night", "tom")

    assert calls[0]["path"] == "/v1/dispatch/shift"
    assert calls[0]["method"] == "POST"
    assert calls[0]["payload"]["kind"] == "night"
    assert resp["title"] == "Dispatch Shift"
    assert "3f2b1c00-0000-4000-8000-000000000001" in resp["text"]


def test_shift_never_sends_a_slot(http_backend, monkeypatch):
    """`slot` must always be null.

    dispatchd appends a non-null slot to the child argv (`spawn_shift` in
    metaframework `dispatchd/actions.py`), but `dispatch`'s top-level parser
    takes exactly one positional — so `dispatch dayshift 9am` exits 2 before
    doing any work. The endpoint has already returned 202 with a run_id and
    written a "running" registry row by then, so the failure is invisible:
    Slack says spawned, and nothing ran. Until that is fixed server-side,
    the only safe slot this client can send is none at all.
    """
    calls = _stub_post(monkeypatch, _shift_envelope("day"))
    dispatch_plugin.handle("dispatch shift day", "tom")
    assert calls[0]["payload"] == {"kind": "day", "slot": None}


def test_shift_reply_says_spawned_not_running(http_backend, monkeypatch):
    """meta#438: the in-flight registry only knows runs dispatchd itself
    started, so a 202 during a launchd shift is real and the child then loses
    the LockManager race. The copy must not promise it is running."""
    _stub_post(monkeypatch, _shift_envelope("night"))
    text = dispatch_plugin.handle("dispatch shift night", "tom")["text"]

    assert "spawned" in text.lower()
    assert "dispatch check" in text
    lowered = text.lower()
    for overclaim in ("is running", "now running", "started running"):
        assert overclaim not in lowered


def test_shift_forbidden_names_the_shift_capability(http_backend, monkeypatch):
    """403 on this endpoint means the key lacks `shift` — not `work`. Getting
    this wrong sends Tom to edit the wrong line of keys.toml."""
    body = json.dumps({"error": "forbidden", "message": "key missing capability: shift"}).encode()

    def fake(path, *, method="GET", payload=None):
        raise urllib.error.HTTPError("u", 403, "forbidden", {}, io.BytesIO(body))

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", fake)
    text = dispatch_plugin.handle("dispatch shift night", "tom")["text"]
    assert "shift" in text
    assert "work" not in text.lower()


def test_shift_conflict_does_not_claim_a_global_mutex(http_backend, monkeypatch):
    body = json.dumps({"error": "conflict", "message": "another shift is already running"}).encode()

    def fake(path, *, method="GET", payload=None):
        raise urllib.error.HTTPError("u", 409, "conflict", {}, io.BytesIO(body))

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", fake)
    text = dispatch_plugin.handle("dispatch shift night", "tom")["text"].lower()
    assert "dispatch check" in text
    for overclaim in ("global", "mutex", "nothing else can run", "only one run"):
        assert overclaim not in text


def test_shift_bad_request_echoes_the_servers_valid_kinds(http_backend, monkeypatch):
    """The client deliberately does not keep its own copy of the kind
    vocabulary. dispatchd's 400 already lists the valid set, and echoing it
    means a kind added server-side is never refused by a stale client list."""
    body = json.dumps(
        {
            "error": "bad_request",
            "message": (
                "unknown shift kind: 'nite'. valid: day, night, pmreview, sanity, selffix, wrapup"
            ),
        }
    ).encode()

    def fake(path, *, method="GET", payload=None):
        raise urllib.error.HTTPError("u", 400, "bad request", {}, io.BytesIO(body))

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", fake)
    text = dispatch_plugin.handle("dispatch shift nite", "tom")["text"]
    assert "nite" in text
    assert "pmreview" in text


def test_shift_4xx_is_not_captured_but_5xx_is(http_backend, monkeypatch):
    """A busy daemon or a missing cap is control flow, not an incident."""
    captured: list[Exception] = []
    monkeypatch.setattr(dispatch_plugin, "capture", lambda e, **k: captured.append(e))

    def raise_code(code):
        body = json.dumps({"error": "conflict", "message": "busy"}).encode()

        def fake(path, *, method="GET", payload=None):
            raise urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(body))

        return fake

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", raise_code(409))
    dispatch_plugin.handle("dispatch shift night", "tom")
    assert captured == []

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", raise_code(503))
    dispatch_plugin.handle("dispatch shift night", "tom")
    assert len(captured) == 1


def test_shift_non_json_error_body_does_not_crash(http_backend, monkeypatch):
    def fake(path, *, method="GET", payload=None):
        raise urllib.error.HTTPError("u", 502, "bad gateway", {}, io.BytesIO(b"<html>nope</html>"))

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", fake)
    assert "502" in dispatch_plugin.handle("dispatch shift night", "tom")["text"]


def test_shift_unreachable_daemon_is_friendly(http_backend, monkeypatch):
    def fake(path, *, method="GET", payload=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(dispatch_plugin, "_call_dispatchd", fake)
    assert "unreachable" in dispatch_plugin.handle("dispatch shift night", "tom")["text"]


def test_shift_does_not_swallow_the_read_commands(http_backend, monkeypatch):
    """The shift matcher is anchored, so `dispatch status` must still read."""
    _stub_call(monkeypatch, {"data": {"text": "## Current Status\nall good"}})
    assert "all good" in dispatch_plugin.handle("dispatch status", "tom")["text"]


def test_matcher_routes_a_shift_message_to_this_plugin():
    """End-to-end through sandy's own matcher: `commands` must carry the phrase
    or the plugin is never consulted, however good the internal parser is."""
    assert dispatch_plugin in matcher.find_matches("dispatch shift night", [dispatch_plugin])
