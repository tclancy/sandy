import random
import re

import requests

name = "cryptics"
commands = ["crossword"]

ARCHIVE_URL = "https://coxrathvon.com/"
PUZZLE_URL = "https://coxrathvon.com/puzzles/{puzzle_id}/pdf"
PUZZLE_PATTERN = re.compile(r'href="/puzzles/([^"]+)"')


def _fetch_puzzle_ids(archive_url: str = ARCHIVE_URL) -> list[str]:
    """Fetch all puzzle IDs from the Hex archive homepage."""
    response = requests.get(archive_url, timeout=10)
    response.raise_for_status()
    return PUZZLE_PATTERN.findall(response.text)


def _resolve_pdf_url(puzzle_id: str) -> str:
    """Follow the /pdf redirect to get the signed GCS URL."""
    url = PUZZLE_URL.format(puzzle_id=puzzle_id)
    response = requests.get(url, timeout=10, allow_redirects=True)
    response.raise_for_status()
    return response.url


def handle(text: str, actor: str) -> str:
    try:
        puzzle_ids = _fetch_puzzle_ids()
    except Exception as e:
        return f"Couldn't fetch crossword archive: {e}"

    if not puzzle_ids:
        return "No puzzles found in the archive."

    puzzle_id = random.choice(puzzle_ids)
    puzzle_page = f"https://coxrathvon.com/puzzles/{puzzle_id}"

    try:
        pdf_url = _resolve_pdf_url(puzzle_id)
    except Exception as e:
        return f"Found puzzle {puzzle_page} but couldn't resolve PDF: {e}"

    return f"Here's your cryptic crossword:\n{puzzle_page}\nPDF: {pdf_url}"
