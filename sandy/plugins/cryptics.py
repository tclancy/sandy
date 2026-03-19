import random
import re

import requests

name = "cryptics"
commands = ["crossword"]

# --- Hex (Cox & Rathvon) ---

_HEX_ARCHIVE_URL = "https://coxrathvon.com/"
_HEX_PUZZLE_PATTERN = re.compile(r'href="/puzzles/([^"]+)"')


def _fetch_hex() -> tuple[str, str]:
    """Return (puzzle_page_url, pdf_url) for a random Hex puzzle."""
    response = requests.get(_HEX_ARCHIVE_URL, timeout=10)
    response.raise_for_status()
    puzzle_ids = _HEX_PUZZLE_PATTERN.findall(response.text)
    if not puzzle_ids:
        raise ValueError("No puzzles found in Hex archive.")
    puzzle_id = random.choice(puzzle_ids)
    puzzle_page = f"https://coxrathvon.com/puzzles/{puzzle_id}"
    pdf_response = requests.get(f"{puzzle_page}/pdf", timeout=10, allow_redirects=True)
    pdf_response.raise_for_status()
    return puzzle_page, pdf_response.url


# --- Mad Dog Cryptics ---

_MAD_DOG_URL = "https://maddogcryptics.com/"
_MAD_DOG_TITLE_PATTERN = re.compile(r"Mad Dog Cryptics #(\d+)</h2>")
_MAD_DOG_PDF_PATTERN = re.compile(r'href="([^"]+\.pdf[^"]*)"')


def _fetch_mad_dog() -> tuple[str, str]:
    """Return (puzzle_page_url, pdf_url) for a random Mad Dog Cryptics puzzle."""
    response = requests.get(_MAD_DOG_URL, timeout=10)
    response.raise_for_status()
    html = response.text

    # Find all puzzle numbers, then pick one and find its PDF link.
    numbers = _MAD_DOG_TITLE_PATTERN.findall(html)
    if not numbers:
        raise ValueError("No puzzles found on Mad Dog Cryptics.")
    number = random.choice(numbers)

    # Find the section for this puzzle number and extract the first PDF href.
    section_match = re.search(rf"Mad Dog Cryptics #{number}</h2>(.*?)(?=<h2|$)", html, re.DOTALL)
    if not section_match:
        raise ValueError(f"Couldn't find section for Mad Dog Cryptics #{number}.")
    pdf_match = _MAD_DOG_PDF_PATTERN.search(section_match.group(1))
    if not pdf_match:
        raise ValueError(f"Couldn't find PDF link for Mad Dog Cryptics #{number}.")

    puzzle_page = f"{_MAD_DOG_URL}#{number}"
    return puzzle_page, pdf_match.group(1)


# --- Sources registry ---

SOURCES = [
    ("Hex", _fetch_hex),
    ("Mad Dog Cryptics", _fetch_mad_dog),
]


def handle(text: str, actor: str) -> dict:
    source_name, fetcher = random.choice(SOURCES)
    try:
        puzzle_page, pdf_url = fetcher()
    except Exception as e:
        return {"text": f"Couldn't fetch a crossword from {source_name}: {e}"}

    return {
        "text": f"Sending your crossword from {source_name} to the printer.",
        "pdf_url": pdf_url,
        "links": [{"label": f"View puzzle online ({source_name})", "url": puzzle_page}],
    }
