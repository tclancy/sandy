"""Real Men of Genius plugin.

Scrapes allowe.com for Bud Light Real Men of Genius mp3 links,
picks one at random, and plays it locally via afplay (macOS).
"""

import os
import random
import re
import subprocess
import tempfile

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


def _play_mp3(url: str) -> None:
    """Download *url* to a temp file and play it with afplay."""
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(response.content)
        tmp_path = f.name
    try:
        subprocess.run(["afplay", tmp_path], check=True)
    finally:
        os.unlink(tmp_path)


def handle(text: str, actor: str) -> dict:
    urls = _get_mp3_urls()
    if not urls:
        raise ValueError("No Real Men of Genius tracks found.")
    url = random.choice(urls)
    # Decode the filename for a readable title
    filename = url.split("/")[-1]
    title = requests.utils.unquote(filename).removesuffix(".mp3")
    _play_mp3(url)
    return {"text": f"Real Men of Genius presents: {title}"}
