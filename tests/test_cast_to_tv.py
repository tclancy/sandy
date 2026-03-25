"""Tests for the cast_to_tv plugin."""

from unittest.mock import MagicMock, patch

import pytest

from sandy.plugins import cast_to_tv


# ---------------------------------------------------------------------------
# _mime_from_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://example.com/video.mp4", "video/mp4"),
        ("https://example.com/stream.m3u8", "application/x-mpegURL"),
        ("https://example.com/track.mp3", "audio/mpeg"),
        ("https://example.com/image.jpg", "image/jpeg"),
        ("https://example.com/image.jpeg", "image/jpeg"),
        ("https://example.com/image.png", "image/png"),
        ("https://example.com/unknown", "video/mp4"),  # default
        ("https://example.com/page?q=foo&bar=baz", "video/mp4"),  # query params, no ext
    ],
)
def test_mime_from_url(url, expected):
    assert cast_to_tv._mime_from_url(url) == expected


# ---------------------------------------------------------------------------
# _device_name / _discovery_timeout
# ---------------------------------------------------------------------------


def test_device_name_default():
    with patch.dict("os.environ", {}, clear=True):
        os.environ.pop("CAST_DEVICE_NAME", None)
        assert cast_to_tv._device_name() == "Living Room TV"


def test_device_name_from_env(monkeypatch):
    monkeypatch.setenv("CAST_DEVICE_NAME", "Bedroom TV")
    assert cast_to_tv._device_name() == "Bedroom TV"


def test_discovery_timeout_default(monkeypatch):
    monkeypatch.delenv("CAST_TIMEOUT", raising=False)
    assert cast_to_tv._discovery_timeout() == 10


def test_discovery_timeout_from_env(monkeypatch):
    monkeypatch.setenv("CAST_TIMEOUT", "5")
    assert cast_to_tv._discovery_timeout() == 5


import os  # noqa: E402  (needs to come after fixture definitions above)


# ---------------------------------------------------------------------------
# handle — no URL
# ---------------------------------------------------------------------------


def test_handle_cast_no_url():
    result = cast_to_tv.handle("cast to tv", actor="tom")
    assert result["title"] == "Cast to TV"
    assert "No URL found" in result["text"]


def test_handle_cast_this_no_url():
    result = cast_to_tv.handle("cast this please", actor="tom")
    assert "No URL found" in result["text"]


# ---------------------------------------------------------------------------
# handle — cast a URL (success path)
# ---------------------------------------------------------------------------


def _make_mock_cast():
    """Return a mock (cast, browser) pair."""
    mc = MagicMock()
    cast = MagicMock()
    cast.media_controller = mc
    browser = MagicMock()
    return cast, browser


def test_handle_cast_url_success(monkeypatch):
    cast, browser = _make_mock_cast()

    with patch.object(cast_to_tv, "_get_cast", return_value=(cast, browser)):
        result = cast_to_tv.handle(
            "cast to tv https://example.com/movie.mp4",
            actor="tom",
        )

    assert result["title"] == "Cast to TV"
    assert "Now casting" in result["text"]
    assert result["links"][0]["url"] == "https://example.com/movie.mp4"
    cast.media_controller.play_media.assert_called_once_with(
        "https://example.com/movie.mp4", "video/mp4"
    )
    cast.media_controller.block_until_active.assert_called_once()


def test_handle_cast_url_with_progress(monkeypatch):
    cast, browser = _make_mock_cast()
    progress_calls = []

    with patch.object(cast_to_tv, "_get_cast", return_value=(cast, browser)):
        cast_to_tv.handle(
            "cast this https://example.com/stream.m3u8",
            actor="tom",
            progress=progress_calls.append,
        )

    assert any("Connecting" in c for c in progress_calls)
    assert any("Casting" in c for c in progress_calls)


def test_handle_cast_url_strips_trailing_punctuation():
    cast, browser = _make_mock_cast()

    with patch.object(cast_to_tv, "_get_cast", return_value=(cast, browser)):
        cast_to_tv.handle(
            "cast to tv https://example.com/clip.mp4.",
            actor="tom",
        )

    played_url = cast.media_controller.play_media.call_args[0][0]
    assert not played_url.endswith(".")
    assert played_url == "https://example.com/clip.mp4"


# ---------------------------------------------------------------------------
# handle — device not found
# ---------------------------------------------------------------------------


def test_handle_cast_device_not_found():
    with patch.object(cast_to_tv, "_get_cast", side_effect=RuntimeError("No Chromecast found")):
        result = cast_to_tv.handle("cast to tv https://example.com/video.mp4", actor="tom")

    assert "No Chromecast found" in result["text"]


# ---------------------------------------------------------------------------
# handle — stop casting
# ---------------------------------------------------------------------------


def test_handle_stop_casting_success():
    cast, browser = _make_mock_cast()

    with patch.object(cast_to_tv, "_get_cast", return_value=(cast, browser)):
        result = cast_to_tv.handle("stop casting", actor="tom")

    assert "Stopped cast" in result["text"]
    cast.quit_app.assert_called_once()


def test_handle_stop_casting_device_not_found():
    with patch.object(cast_to_tv, "_get_cast", side_effect=RuntimeError("No Chromecast found")):
        result = cast_to_tv.handle("stop casting", actor="tom")

    assert "No Chromecast found" in result["text"]


def test_handle_stop_casting_with_progress():
    cast, browser = _make_mock_cast()
    progress_calls = []

    with patch.object(cast_to_tv, "_get_cast", return_value=(cast, browser)):
        cast_to_tv.handle("stop casting", actor="tom", progress=progress_calls.append)

    assert any("Stopping" in c for c in progress_calls)


# ---------------------------------------------------------------------------
# _cleanup — does not raise even if everything throws
# ---------------------------------------------------------------------------


def test_cleanup_is_fault_tolerant():
    cast = MagicMock()
    cast.disconnect.side_effect = Exception("boom")
    browser = MagicMock()

    with patch.dict("sys.modules", {"pychromecast": MagicMock()}):
        cast_to_tv._cleanup(cast, browser)  # must not raise
