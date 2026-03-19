"""Tests for the real_men plugin."""

from unittest.mock import MagicMock, patch

import pytest

import sandy.plugins.real_men as real_men


_SAMPLE_HTML = """
<html><body>
<a href="/audio/BudLite/Mr%20Amazing%20Guy.mp3">Mr. Amazing Guy</a>
<a href="/audio/BudLite/Mr%20Other%20Dude.mp3">Mr. Other Dude</a>
<a href="/about">About</a>
</body></html>
"""


def _mock_page_response():
    resp = MagicMock()
    resp.text = _SAMPLE_HTML
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# Module attributes
# ---------------------------------------------------------------------------


def test_name():
    assert real_men.name == "real_men"


def test_commands_include_expected():
    for phrase in ["real man", "real men", "tell me about a real man"]:
        assert phrase in real_men.commands


# ---------------------------------------------------------------------------
# _get_mp3_urls
# ---------------------------------------------------------------------------


def test_get_mp3_urls_extracts_links():
    with patch("requests.get", return_value=_mock_page_response()):
        urls = real_men._get_mp3_urls()
    assert len(urls) == 2
    assert "https://allowe.com/audio/BudLite/Mr%20Amazing%20Guy.mp3" in urls
    assert "https://allowe.com/audio/BudLite/Mr%20Other%20Dude.mp3" in urls


def test_get_mp3_urls_empty_page():
    resp = MagicMock()
    resp.text = "<html></html>"
    resp.raise_for_status = MagicMock()
    with patch("requests.get", return_value=resp):
        urls = real_men._get_mp3_urls()
    assert urls == []


# ---------------------------------------------------------------------------
# handle
# ---------------------------------------------------------------------------


def test_handle_returns_response_with_audio_url(monkeypatch):
    monkeypatch.setattr(
        real_men,
        "_get_mp3_urls",
        lambda: ["https://allowe.com/audio/BudLite/Mr%20Amazing%20Guy.mp3"],
    )

    result = real_men.handle("tell me about a real man", "tom")
    assert "Amazing Guy" in result["text"]
    assert "Real Men of Genius" in result["text"]
    assert result["audio_url"] == "https://allowe.com/audio/BudLite/Mr%20Amazing%20Guy.mp3"
    assert len(result["links"]) == 1
    assert result["links"][0]["label"] == "Listen"


def test_handle_raises_when_no_tracks(monkeypatch):
    monkeypatch.setattr(real_men, "_get_mp3_urls", lambda: [])
    with pytest.raises(ValueError, match="No Real Men of Genius tracks found"):
        real_men.handle("real man", "tom")
