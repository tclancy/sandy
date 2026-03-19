"""Real Men of Genius plugin.

Scrapes allowe.com for Bud Light Real Men of Genius mp3 links,
picks one at random, and returns the title and audio URL.
CLI auto-plays locally; remote transports render it as a link.
"""

import random
import re

import requests

name = "real_men"
commands = ["real man", "real men", "tell me about a real man"]

_PAGE_URL = "https://allowe.com/humor/audio/real-men-of-genius.html"
_BASE_URL = "https://allowe.com"
_MP3_PATTERN = re.compile(r'href="(/audio/[^"]+\.mp3)"')


def _get_mp3_urls() -> list[str]:
    """Fetch the archive page and return all absolute mp3 URLs."""
    response = requests.get(_PAGE_URL, timeout=10)
    response.raise_for_status()
    paths = _MP3_PATTERN.findall(response.text)
    return [f"{_BASE_URL}{path}" for path in paths]


def handle(text: str, actor: str) -> dict:
    urls = _get_mp3_urls()
    if not urls:
        raise ValueError("No Real Men of Genius tracks found.")
    url = random.choice(urls)
    # Decode the filename for a readable title
    filename = url.split("/")[-1]
    title = requests.utils.unquote(filename).removesuffix(".mp3")
    return {
        "text": f"Real Men of Genius presents: {title}",
        "audio_url": url,
        "links": [{"label": "Listen", "url": url}],
    }
