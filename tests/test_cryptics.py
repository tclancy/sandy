from unittest.mock import patch, MagicMock

from sandy.plugins import cryptics


FAKE_ARCHIVE_HTML = """
<a href="/puzzles/abc123">Puzzle One</a>
<a href="/puzzles/def456">Puzzle Two</a>
<a href="/puzzles/ghi789">Puzzle Three</a>
"""


def test_cryptics_name():
    assert cryptics.name == "cryptics"


def test_cryptics_commands():
    assert "crossword" in cryptics.commands


def test_fetch_puzzle_ids_parses_links():
    mock_response = MagicMock()
    mock_response.text = FAKE_ARCHIVE_HTML
    with patch("sandy.plugins.cryptics.requests.get", return_value=mock_response):
        ids = cryptics._fetch_puzzle_ids()
    assert ids == ["abc123", "def456", "ghi789"]


def test_resolve_pdf_url_follows_redirect():
    mock_response = MagicMock()
    mock_response.url = "https://storage.googleapis.com/bucket/puzzle.pdf?sig=abc"
    with patch("sandy.plugins.cryptics.requests.get", return_value=mock_response):
        url = cryptics._resolve_pdf_url("abc123")
    assert url == "https://storage.googleapis.com/bucket/puzzle.pdf?sig=abc"


def test_handle_returns_puzzle_and_pdf():
    pdf_url = "https://storage.googleapis.com/bucket/puzzle.pdf?sig=abc"
    with patch.object(cryptics, "_fetch_puzzle_ids", return_value=["abc123"]):
        with patch.object(cryptics, "_resolve_pdf_url", return_value=pdf_url):
            result = cryptics.handle("crossword, please", "tom")
    assert "https://coxrathvon.com/puzzles/abc123" in result
    assert pdf_url in result


def test_handle_archive_fetch_failure():
    with patch.object(cryptics, "_fetch_puzzle_ids", side_effect=Exception("timeout")):
        result = cryptics.handle("crossword, please", "tom")
    assert "couldn't fetch" in result.lower()


def test_handle_empty_archive():
    with patch.object(cryptics, "_fetch_puzzle_ids", return_value=[]):
        result = cryptics.handle("crossword, please", "tom")
    assert "no puzzles" in result.lower()


def test_handle_pdf_resolve_failure():
    with patch.object(cryptics, "_fetch_puzzle_ids", return_value=["abc123"]):
        with patch.object(cryptics, "_resolve_pdf_url", side_effect=Exception("404")):
            result = cryptics.handle("crossword, please", "tom")
    assert "couldn't resolve pdf" in result.lower()
    assert "coxrathvon.com/puzzles/abc123" in result
