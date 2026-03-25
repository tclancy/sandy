"""Cast to TV Sandy plugin.

Sends a URL to the Living Room TV (Chromecast/Google TV) via pychromecast.

Commands:
  "cast to tv <url>"   — cast the URL to the TV
  "cast this <url>"    — same shorthand
  "stop casting"       — quit the active cast app on the TV

Configuration (sandy.toml [cast_to_tv] section):
  CAST_DEVICE_NAME  — friendly name of the Chromecast (default: "Living Room TV")
  CAST_TIMEOUT      — seconds to wait for device discovery (default: 10)

Requires:
  pip install pychromecast
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

name = "cast_to_tv"
commands = ["cast to tv", "cast this", "stop casting"]

_DEFAULT_DEVICE = "Living Room TV"
_URL_RE = re.compile(r"https?://\S+")

# MIME type heuristics — Chromecast needs a content_type for play_media
_MIME_BY_EXT = {
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".m3u8": "application/x-mpegURL",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
}


def _mime_from_url(url: str) -> str:
    """Best-effort MIME type from URL extension; default to video/mp4."""
    path = urlparse(url).path.lower()
    for ext, mime in _MIME_BY_EXT.items():
        if path.endswith(ext):
            return mime
    return "video/mp4"


def _device_name() -> str:
    return os.environ.get("CAST_DEVICE_NAME", _DEFAULT_DEVICE)


def _discovery_timeout() -> int:
    return int(os.environ.get("CAST_TIMEOUT", "10"))


def _get_cast():
    """Return (cast, browser) or raise RuntimeError."""
    import pychromecast

    name_ = _device_name()
    chromecasts, browser = pychromecast.get_listed_chromecasts(
        friendly_names=[name_],
        timeout=_discovery_timeout(),
    )
    if not chromecasts:
        pychromecast.discovery.stop_discovery(browser)
        raise RuntimeError(f"No Chromecast found with name '{name_}'. Are you on the same LAN?")
    cast = chromecasts[0]
    cast.wait()
    return cast, browser


def _cleanup(cast, browser) -> None:
    try:
        cast.disconnect()
    except Exception:
        pass
    try:
        import pychromecast

        pychromecast.discovery.stop_discovery(browser)
    except Exception:
        pass


def handle(text: str, actor: str, progress=None) -> dict:
    text_lower = text.lower().strip()

    # --- stop casting ---
    if "stop casting" in text_lower:
        if progress:
            progress(f"Stopping cast on {_device_name()}...")
        try:
            cast, browser = _get_cast()
            cast.quit_app()
            _cleanup(cast, browser)
        except RuntimeError as exc:
            return {"title": "Cast to TV", "text": str(exc)}
        return {"title": "Cast to TV", "text": f"Stopped cast on {_device_name()}."}

    # --- cast a URL ---
    match = _URL_RE.search(text)
    if not match:
        return {
            "title": "Cast to TV",
            "text": (
                "No URL found. Usage: 'cast to tv <url>' or 'cast this <url>'.\n"
                "To stop: 'stop casting'."
            ),
        }

    url = match.group(0).rstrip(".,;)")
    content_type = _mime_from_url(url)
    device = _device_name()

    if progress:
        progress(f"Connecting to {device}...")

    try:
        cast, browser = _get_cast()
    except RuntimeError as exc:
        return {"title": "Cast to TV", "text": str(exc)}

    try:
        mc = cast.media_controller
        if progress:
            progress(f"Casting to {device}...")
        mc.play_media(url, content_type)
        mc.block_until_active(timeout=10)
    finally:
        _cleanup(cast, browser)

    return {
        "title": "Cast to TV",
        "text": f"Now casting on {device}.",
        "links": [{"label": "Open URL", "url": url}],
    }
