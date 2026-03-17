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


# --- _print_pdf ---


def _mock_print_pdf(tmp_path, extra_patches=None):
    """Helper: patch all I/O in _print_pdf and return mock_run."""
    pdf_content = b"%PDF fake content"
    mock_response = MagicMock(content=pdf_content)
    mock_file = MagicMock()
    mock_file.name = str(tmp_path / "puzzle.pdf")
    patches = [
        patch("sandy.plugins.cryptics.requests.get", return_value=mock_response),
        patch("sandy.plugins.cryptics.subprocess.run"),
        patch("sandy.plugins.cryptics.tempfile.NamedTemporaryFile"),
        patch("sandy.plugins.cryptics.os.unlink"),
        patch("sandy.plugins.cryptics.os.path.exists", return_value=False),
    ]
    return patches, mock_file


def test_print_pdf_downloads_and_prints(tmp_path):
    patches, mock_file = _mock_print_pdf(tmp_path)
    with patches[0], patches[1] as mock_run, patches[2] as mock_tmp, patches[3], patches[4]:
        mock_tmp.return_value.__enter__.return_value = mock_file
        cryptics._print_pdf("https://example.com/puzzle.pdf")

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "lpr"
    assert "-P" in args


def test_print_pdf_uses_sandy_printer_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDY_PRINTER", "My_Custom_Printer")
    patches, mock_file = _mock_print_pdf(tmp_path)
    with patches[0], patches[1] as mock_run, patches[2] as mock_tmp, patches[3], patches[4]:
        mock_tmp.return_value.__enter__.return_value = mock_file
        cryptics._print_pdf("https://example.com/puzzle.pdf")

    args = mock_run.call_args[0][0]
    assert "My_Custom_Printer" in args


# --- handle ---


def test_handle_prints_and_confirms():
    with patch.object(
        cryptics,
        "_fetch_hex",
        return_value=("https://example.com/p1", "https://example.com/p1.pdf"),
    ):
        with patch(
            "sandy.plugins.cryptics.random.choice", return_value=("Hex", cryptics._fetch_hex)
        ):
            with patch.object(cryptics, "_print_pdf") as mock_print:
                result = cryptics.handle("crossword", "tom")

    mock_print.assert_called_once_with("https://example.com/p1.pdf")
    assert "Printing" in result["text"]
    assert "Hex" in result["text"]
    assert "http" not in result["text"]  # no URL in happy-path output


def test_handle_fetch_failure():
    def boom():
        raise Exception("network error")

    with patch("sandy.plugins.cryptics.random.choice", return_value=("Hex", boom)):
        result = cryptics.handle("crossword", "tom")
    assert "couldn't fetch" in result["text"].lower()
    assert "Hex" in result["text"]


def test_handle_print_failure_includes_puzzle_url():
    with patch.object(
        cryptics,
        "_fetch_hex",
        return_value=("https://example.com/p1", "https://example.com/p1.pdf"),
    ):
        with patch(
            "sandy.plugins.cryptics.random.choice", return_value=("Hex", cryptics._fetch_hex)
        ):
            with patch.object(cryptics, "_print_pdf", side_effect=Exception("printer offline")):
                result = cryptics.handle("crossword", "tom")

    assert "printing failed" in result["text"].lower()
    links = result.get("links", [])
    assert any("example.com/p1" in link.get("url", "") for link in links)
