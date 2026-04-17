"""Tests for sandy.oauth_server — Spotify OAuth callback server."""

import threading
from unittest.mock import MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from sandy import oauth_server


# ---------------------------------------------------------------------------
# Module-level state helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_pending_oauth():
    """Ensure _pending_oauth is cleared before and after each test."""
    oauth_server.clear_pending_oauth()
    yield
    oauth_server.clear_pending_oauth()


# ---------------------------------------------------------------------------
# set_pending_oauth / clear_pending_oauth / get_pending_oauth
# ---------------------------------------------------------------------------


def test_set_and_get_pending_oauth():
    manager = MagicMock()
    oauth_server.set_pending_oauth(manager, "test-state")
    mgr, state = oauth_server.get_pending_oauth()
    assert mgr is manager
    assert state == "test-state"


def test_clear_pending_oauth():
    oauth_server.set_pending_oauth(MagicMock(), "some-state")
    oauth_server.clear_pending_oauth()
    mgr, state = oauth_server.get_pending_oauth()
    assert mgr is None
    assert state is None


def test_set_pending_oauth_thread_safe():
    """set/clear from multiple threads must not corrupt state."""
    managers = [MagicMock() for _ in range(10)]
    errors = []

    def writer(mgr):
        try:
            oauth_server.set_pending_oauth(mgr, "state-" + str(id(mgr)))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(m,)) for m in managers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    # State is consistent (some manager or None, not corrupt)
    mgr, state = oauth_server.get_pending_oauth()
    assert mgr is None or mgr in managers


# ---------------------------------------------------------------------------
# get_configured_port
# ---------------------------------------------------------------------------


def test_get_configured_port_set(monkeypatch):
    monkeypatch.setenv("OAUTH_SERVER_PORT", "8888")
    assert oauth_server.get_configured_port() == 8888


def test_get_configured_port_not_set(monkeypatch):
    monkeypatch.delenv("OAUTH_SERVER_PORT", raising=False)
    assert oauth_server.get_configured_port() is None


def test_get_configured_port_empty_string(monkeypatch):
    monkeypatch.setenv("OAUTH_SERVER_PORT", "")
    assert oauth_server.get_configured_port() is None


def test_get_configured_port_invalid(monkeypatch):
    monkeypatch.setenv("OAUTH_SERVER_PORT", "notaport")
    assert oauth_server.get_configured_port() is None


def test_get_configured_port_out_of_range(monkeypatch):
    monkeypatch.setenv("OAUTH_SERVER_PORT", "99999")
    assert oauth_server.get_configured_port() is None


# ---------------------------------------------------------------------------
# HTTP callback endpoint — /callback
# ---------------------------------------------------------------------------


@pytest.fixture
async def client():
    app = oauth_server.build_app()
    async with TestClient(TestServer(app)) as c:
        yield c


@pytest.mark.asyncio
async def test_callback_missing_code(client):
    resp = await client.get("/callback")
    assert resp.status == 400
    body = await resp.text()
    assert "No authorization code" in body


@pytest.mark.asyncio
async def test_callback_error_param(client):
    resp = await client.get("/callback?error=access_denied")
    assert resp.status == 400
    body = await resp.text()
    assert "access_denied" in body


@pytest.mark.asyncio
async def test_callback_no_pending_oauth(client):
    """Code present but no login session registered → 400."""
    resp = await client.get("/callback?code=abc123&state=anystate")
    assert resp.status == 400
    body = await resp.text()
    assert "No active login session" in body


@pytest.mark.asyncio
async def test_callback_state_mismatch(client):
    """State in callback does not match registered state → 400 (CSRF guard)."""
    mock_manager = MagicMock()
    oauth_server.set_pending_oauth(mock_manager, "expected-state")

    resp = await client.get("/callback?code=abc123&state=wrong-state")
    assert resp.status == 400
    body = await resp.text()
    assert "could not be verified" in body.lower()
    # Manager must NOT be consumed — session still valid for a legitimate retry
    mgr, _ = oauth_server.get_pending_oauth()
    assert mgr is mock_manager


@pytest.mark.asyncio
async def test_callback_missing_state(client):
    """Callback arrives without a state parameter → 400 (CSRF guard)."""
    mock_manager = MagicMock()
    oauth_server.set_pending_oauth(mock_manager, "expected-state")

    resp = await client.get("/callback?code=abc123")
    assert resp.status == 400
    body = await resp.text()
    assert "could not be verified" in body.lower()


@pytest.mark.asyncio
async def test_callback_success(client):
    """Valid code and matching state with pending OAuth manager → token exchange succeeds."""
    mock_manager = MagicMock()
    mock_manager.get_access_token.return_value = {"access_token": "tok"}
    oauth_server.set_pending_oauth(mock_manager, "good-state")

    resp = await client.get("/callback?code=validcode&state=good-state")
    assert resp.status == 200
    body = await resp.text()
    assert "Authorization complete" in body

    mock_manager.get_access_token.assert_called_once_with("validcode", check_cache=False)
    # Manager and state should be cleared after success
    mgr, state = oauth_server.get_pending_oauth()
    assert mgr is None
    assert state is None


@pytest.mark.asyncio
async def test_callback_token_exchange_error(client):
    """Token exchange exception → 500 response; manager stays in place so user can retry."""
    mock_manager = MagicMock()
    mock_manager.get_access_token.side_effect = Exception("network error")
    oauth_server.set_pending_oauth(mock_manager, "good-state")

    resp = await client.get("/callback?code=badcode&state=good-state")
    assert resp.status == 500
    body = await resp.text()
    assert "Token exchange error" in body
    # Manager must survive a failed exchange so the user can retry without re-running music login
    mgr, _ = oauth_server.get_pending_oauth()
    assert mgr is mock_manager


# ---------------------------------------------------------------------------
# /health endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status == 200
    body = await resp.text()
    assert body == "ok"
