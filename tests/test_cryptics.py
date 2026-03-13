from unittest.mock import patch, MagicMock

from sandy.plugins import cryptics


FAKE_HEX_HTML = """
<a href="/puzzles/abc123">Puzzle One</a>
<a href="/puzzles/def456">Puzzle Two</a>
"""

FAKE_MAD_DOG_HTML = """
<h2>Mad Dog Cryptics #31</h2>
<a href="https://www.dropbox.com/puzzle31.pdf?dl=0">PDF</a>
<h2>Mad Dog Cryptics #30</h2>
<a href="https://www.dropbox.com/puzzle30.pdf?dl=0">PDF</a>
"""


def test_cryptics_name():
    assert cryptics.name == "cryptics"


def test_cryptics_commands():
    assert "crossword" in cryptics.commands


# --- Hex ---


def test_fetch_hex_returns_puzzle_and_pdf():
    archive_response = MagicMock(text=FAKE_HEX_HTML)
    pdf_response = MagicMock(url="https://storage.googleapis.com/bucket/puzzle.pdf")

    with patch("sandy.plugins.cryptics.requests.get", side_effect=[archive_response, pdf_response]):
        puzzle_page, pdf_url = cryptics._fetch_hex()

    assert "coxrathvon.com/puzzles/" in puzzle_page
    assert pdf_url == "https://storage.googleapis.com/bucket/puzzle.pdf"


def test_fetch_hex_raises_when_no_puzzles():
    empty_response = MagicMock(text="<html>nothing here</html>")
    with patch("sandy.plugins.cryptics.requests.get", return_value=empty_response):
        try:
            cryptics._fetch_hex()
            assert False, "should have raised"
        except ValueError as e:
            assert "No puzzles" in str(e)


# --- Mad Dog ---


def test_fetch_mad_dog_returns_puzzle_and_pdf():
    response = MagicMock(text=FAKE_MAD_DOG_HTML)
    with patch("sandy.plugins.cryptics.requests.get", return_value=response):
        with patch("sandy.plugins.cryptics.random.choice", return_value="31"):
            puzzle_page, pdf_url = cryptics._fetch_mad_dog()

    assert "#31" in puzzle_page
    assert "puzzle31.pdf" in pdf_url


def test_fetch_mad_dog_raises_when_no_puzzles():
    response = MagicMock(text="<html>nothing here</html>")
    with patch("sandy.plugins.cryptics.requests.get", return_value=response):
        try:
            cryptics._fetch_mad_dog()
            assert False, "should have raised"
        except ValueError as e:
            assert "No puzzles" in str(e)


# --- handle ---


def test_handle_returns_source_name_and_links():
    with patch.object(
        cryptics,
        "_fetch_hex",
        return_value=("https://example.com/p1", "https://example.com/p1.pdf"),
    ):
        with patch(
            "sandy.plugins.cryptics.random.choice", return_value=("Hex", cryptics._fetch_hex)
        ):
            result = cryptics.handle("crossword", "tom")
    assert "Hex" in result
    assert "https://example.com/p1" in result
    assert "https://example.com/p1.pdf" in result


def test_handle_fetch_failure():
    def boom():
        raise Exception("network error")

    with patch("sandy.plugins.cryptics.random.choice", return_value=("Hex", boom)):
        result = cryptics.handle("crossword", "tom")
    assert "couldn't fetch" in result.lower()
    assert "Hex" in result
