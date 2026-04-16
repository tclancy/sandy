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

    with patch(
        "sandy.plugins.cryptics.requests.get", side_effect=[archive_response, pdf_response]
    ) as mock_get:
        puzzle_page, pdf_url = cryptics._fetch_hex()

    assert "coxrathvon.com/puzzles/" in puzzle_page
    assert pdf_url == "https://storage.googleapis.com/bucket/puzzle.pdf"
    # The PDF fetch must use ?download=true to get the raw file
    pdf_call_url = mock_get.call_args_list[1][0][0]
    assert pdf_call_url.endswith("/pdf?download=true")


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
    # Dropbox dl=0 (preview) must be rewritten to dl=1 (direct download)
    assert "dl=1" in pdf_url
    assert "dl=0" not in pdf_url


def test_fetch_mad_dog_rewrites_dropbox_dl_param():
    """Dropbox URLs with dl=0 (preview) must become dl=1 (direct download)."""
    html_with_dl0 = """
<h2>Mad Dog Cryptics #5</h2>
<a href="https://www.dropbox.com/scl/fi/abc/puzzle.pdf?rlkey=xyz&dl=0">PDF</a>
"""
    response = MagicMock(text=html_with_dl0)
    with patch("sandy.plugins.cryptics.requests.get", return_value=response):
        with patch("sandy.plugins.cryptics.random.choice", return_value="5"):
            _, pdf_url = cryptics._fetch_mad_dog()

    assert "dl=1" in pdf_url
    assert "dl=0" not in pdf_url
    assert "rlkey=xyz" in pdf_url  # other params preserved


def test_fetch_mad_dog_no_dl_param_unchanged():
    """URLs without a dl parameter should pass through unchanged."""
    html_no_dl = """
<h2>Mad Dog Cryptics #7</h2>
<a href="https://example.com/puzzle7.pdf">PDF</a>
"""
    response = MagicMock(text=html_no_dl)
    with patch("sandy.plugins.cryptics.requests.get", return_value=response):
        with patch("sandy.plugins.cryptics.random.choice", return_value="7"):
            _, pdf_url = cryptics._fetch_mad_dog()

    assert pdf_url == "https://example.com/puzzle7.pdf"


def test_fetch_mad_dog_raises_when_no_puzzles():
    response = MagicMock(text="<html>nothing here</html>")
    with patch("sandy.plugins.cryptics.requests.get", return_value=response):
        try:
            cryptics._fetch_mad_dog()
            assert False, "should have raised"
        except ValueError as e:
            assert "No puzzles" in str(e)


# --- handle ---

_PRINT_CAPS = frozenset({"print"})


def test_handle_returns_pdf_url_with_print_caps():
    with patch.object(
        cryptics,
        "_fetch_hex",
        return_value=("https://example.com/p1", "https://example.com/p1.pdf"),
    ):
        with patch(
            "sandy.plugins.cryptics.random.choice", return_value=("Hex", cryptics._fetch_hex)
        ):
            result = cryptics.handle("crossword", "tom", caps=_PRINT_CAPS)

    assert result.get("pdf_url") == "https://example.com/p1.pdf"
    assert "printer" in result["text"].lower()


def test_handle_omits_pdf_without_print_caps():
    with patch.object(
        cryptics,
        "_fetch_hex",
        return_value=("https://example.com/p1", "https://example.com/p1.pdf"),
    ):
        with patch(
            "sandy.plugins.cryptics.random.choice", return_value=("Hex", cryptics._fetch_hex)
        ):
            result = cryptics.handle("crossword", "alice")

    assert "pdf_url" not in result
    assert "Hex" in result["text"]


def test_handle_includes_puzzle_link():
    with patch.object(
        cryptics,
        "_fetch_hex",
        return_value=("https://example.com/p1", "https://example.com/p1.pdf"),
    ):
        with patch(
            "sandy.plugins.cryptics.random.choice", return_value=("Hex", cryptics._fetch_hex)
        ):
            result = cryptics.handle("crossword", "tom", caps=_PRINT_CAPS)

    links = result.get("links", [])
    assert any("example.com/p1" in link.get("url", "") for link in links)


def test_handle_includes_source_name():
    with patch.object(
        cryptics,
        "_fetch_hex",
        return_value=("https://example.com/p1", "https://example.com/p1.pdf"),
    ):
        with patch(
            "sandy.plugins.cryptics.random.choice", return_value=("Hex", cryptics._fetch_hex)
        ):
            result = cryptics.handle("crossword", "tom")

    assert "Hex" in result.get("text", "")


def test_handle_fetch_failure():
    def boom():
        raise Exception("network error")

    with patch("sandy.plugins.cryptics.random.choice", return_value=("Hex", boom)):
        result = cryptics.handle("crossword", "tom")
    assert "couldn't fetch" in result["text"].lower()
    assert "Hex" in result["text"]
