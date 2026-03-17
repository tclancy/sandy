"""Tests for the real_men plugin."""

import subprocess
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


def _mock_mp3_response(content=b"fake-mp3-data"):
    resp = MagicMock()
    resp.content = content
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
# _play_mp3
# ---------------------------------------------------------------------------


def test_play_mp3_downloads_and_plays(tmp_path):
    with (
        patch("requests.get", return_value=_mock_mp3_response()),
        patch("subprocess.run") as mock_run,
        patch("tempfile.NamedTemporaryFile") as mock_tmp,
        patch("os.unlink") as mock_unlink,
    ):
        # Make NamedTemporaryFile work as context manager with a fake path
        fake_file = MagicMock()
        fake_file.__enter__ = MagicMock(return_value=fake_file)
        fake_file.__exit__ = MagicMock(return_value=False)
        fake_file.name = "/tmp/fake.mp3"
        mock_tmp.return_value = fake_file

        real_men._play_mp3("https://example.com/test.mp3")

        mock_run.assert_called_once_with(["afplay", "/tmp/fake.mp3"], check=True)
        mock_unlink.assert_called_once_with("/tmp/fake.mp3")


def test_play_mp3_cleans_up_on_error():
    with (
        patch("requests.get", return_value=_mock_mp3_response()),
        patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "afplay")),
        patch("tempfile.NamedTemporaryFile") as mock_tmp,
        patch("os.unlink") as mock_unlink,
    ):
        fake_file = MagicMock()
        fake_file.__enter__ = MagicMock(return_value=fake_file)
        fake_file.__exit__ = MagicMock(return_value=False)
        fake_file.name = "/tmp/fake.mp3"
        mock_tmp.return_value = fake_file

        with pytest.raises(subprocess.CalledProcessError):
            real_men._play_mp3("https://example.com/test.mp3")

        # Cleanup still ran
        mock_unlink.assert_called_once_with("/tmp/fake.mp3")


# ---------------------------------------------------------------------------
# handle
# ---------------------------------------------------------------------------


def test_handle_returns_title(monkeypatch):
    monkeypatch.setattr(
        real_men,
        "_get_mp3_urls",
        lambda: ["https://allowe.com/audio/BudLite/Mr%20Amazing%20Guy.mp3"],
    )
    monkeypatch.setattr(real_men, "_play_mp3", lambda url: None)

    result = real_men.handle("tell me about a real man", "tom")
    assert "Amazing Guy" in result["text"]
    assert "Real Men of Genius" in result["text"]


def test_handle_raises_when_no_tracks(monkeypatch):
    monkeypatch.setattr(real_men, "_get_mp3_urls", lambda: [])
    with pytest.raises(ValueError, match="No Real Men of Genius tracks found"):
        real_men.handle("real man", "tom")
