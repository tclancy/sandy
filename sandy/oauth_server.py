"""Sandy OAuth callback server.

Listens on a configurable HTTP port and handles provider OAuth redirects.
Currently used by music_discovery to complete Spotify's OAuth flow without
user interaction on the server console.

Usage:
  - Set OAUTH_SERVER_PORT in sandy.toml (e.g. 8888) to enable the server.
  - Expose the port via Cloudflare tunnel so Spotify can redirect back to it.
  - Set SPOTIPY_REDIRECT_URI to the public Cloudflare URL, e.g.
      https://sandy.tomclancy.info/callback
  - Register that URI in your Spotify app's "Redirect URIs" settings.

When the user runs 'music login', Sandy generates the Spotify authorization
URL and returns it via Slack.  The user visits the URL; Spotify redirects to
the callback endpoint below; Sandy exchanges the code for a token (saved to
spotipy's cache file); the browser shows a success page.
"""

import asyncio
import logging
import os
import threading
from html import escape

from aiohttp import web

logger = logging.getLogger(__name__)

# Populated by music_discovery._handle_login(); cleared after successful exchange.
# Access is protected by _lock; both the plugin thread and the async handler touch it.
_pending_oauth = None
_pending_state: str | None = None
_lock = threading.Lock()


def set_pending_oauth(oauth_manager, state: str) -> None:
    """Store the OAuth manager and CSRF state waiting for a callback (called by plugin thread)."""
    with _lock:
        global _pending_oauth, _pending_state
        _pending_oauth = oauth_manager
        _pending_state = state
        logger.debug("Pending OAuth manager registered")


def clear_pending_oauth() -> None:
    """Remove the pending OAuth manager and state (called after successful exchange)."""
    with _lock:
        global _pending_oauth, _pending_state
        _pending_oauth = None
        _pending_state = None


def get_pending_oauth():
    """Return (oauth_manager, state) for the current pending session, or (None, None)."""
    with _lock:
        return _pending_oauth, _pending_state


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------

_SUCCESS_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sandy — Authorization Complete</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 480px;
          margin: 80px auto; text-align: center; }}
  h1 {{ color: #1db954; }}
  p  {{ color: #555; }}
</style>
</head>
<body>
  <h1>✓ Authorization complete</h1>
  <p>Sandy is now connected to Spotify. You can close this tab and return to Slack.</p>
</body>
</html>
"""

_ERROR_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sandy — Authorization Failed</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 480px;
          margin: 80px auto; text-align: center; }}
  h1 {{ color: #e22; }}
  p  {{ color: #555; }}
  code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }}
</style>
</head>
<body>
  <h1>✗ Authorization failed</h1>
  <p>{detail}</p>
  <p>Try running <code>music login</code> again in Slack.</p>
</body>
</html>
"""


async def _handle_callback(request: web.Request) -> web.Response:
    """Handle the Spotify OAuth redirect callback."""
    error = request.query.get("error")
    if error:
        logger.warning("Spotify OAuth error: %s", error)
        html = _ERROR_HTML.format(detail=f"Spotify returned: <code>{escape(error)}</code>")
        return web.Response(text=html, content_type="text/html", status=400)

    code = request.query.get("code")
    if not code:
        logger.warning("OAuth callback missing 'code' query parameter")
        html = _ERROR_HTML.format(detail="No authorization code in callback URL.")
        return web.Response(text=html, content_type="text/html", status=400)

    received_state = request.query.get("state")
    oauth_manager, expected_state = get_pending_oauth()

    if oauth_manager is None:
        logger.warning("OAuth callback received but no pending login session found")
        html = _ERROR_HTML.format(
            detail=(
                "No active login session found. "
                "The session may have expired — run <code>music login</code> again."
            )
        )
        return web.Response(text=html, content_type="text/html", status=400)

    if not received_state or received_state != expected_state:
        logger.warning(
            "OAuth callback state mismatch: received=%r expected=%r", received_state, expected_state
        )
        html = _ERROR_HTML.format(
            detail=(
                "Authorization request could not be verified. "
                "Please run <code>music login</code> again."
            )
        )
        return web.Response(text=html, content_type="text/html", status=400)

    try:
        # Exchange the authorization code for a token.
        # get_access_token() saves the token to spotipy's cache automatically.
        await asyncio.to_thread(oauth_manager.get_access_token, code, check_cache=False)
        logger.info("Spotify OAuth token exchange successful")
        clear_pending_oauth()
        return web.Response(text=_SUCCESS_HTML, content_type="text/html")
    except Exception as exc:
        logger.exception("Spotify token exchange failed")
        html = _ERROR_HTML.format(detail=f"Token exchange error: {escape(str(exc))}")
        return web.Response(text=html, content_type="text/html", status=500)


async def _handle_health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/callback", _handle_callback)
    app.router.add_get("/health", _handle_health)
    return app


async def run_server(port: int) -> None:
    """Start the aiohttp OAuth callback server on *port*.

    Designed to run as an asyncio task alongside Sandy's other transports.
    Handles CancelledError cleanly so the daemon can shut it down without
    log noise.
    """
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    try:
        await site.start()
        logger.info("OAuth callback server listening on port %d", port)
        # Yield control — this task runs indefinitely until cancelled.
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        logger.info("OAuth callback server shutting down")
        raise
    finally:
        await runner.cleanup()


def get_configured_port() -> int | None:
    """Return the OAuth server port from OAUTH_SERVER_PORT env var, or None if not set."""
    raw = os.environ.get("OAUTH_SERVER_PORT", "")
    if not raw:
        return None
    try:
        port = int(raw)
        if not (1 <= port <= 65535):
            raise ValueError
        return port
    except ValueError:
        logger.warning(
            "OAUTH_SERVER_PORT='%s' is not a valid port number — OAuth server disabled", raw
        )
        return None
