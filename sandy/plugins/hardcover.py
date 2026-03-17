"""Hardcover / Dover Library plugin.

"Sandy, suggest a library book" — picks a random book from Tom's
Hardcover "In Dover" list that is also on his "Want to Read" shelf,
then generates a Dover Public Library search URL to reserve it.

Requires HARDCOVER_API_KEY in sandy.toml (or environment).
"""

import os
import random
from urllib.parse import quote_plus

import requests

name = "hardcover"
commands = ["suggest a library book", "library book", "suggest a book"]

_API_URL = "https://api.hardcover.app/v1/graphql"
_KOHA_BASE = "https://librarycatalog.dover.nh.gov/cgi-bin/koha/opac-search.pl"
_KOHA_LIMITS = "&limit=itype%3ABK&limit=branch%3ADOVER"

_STOP_WORDS = {
    "the",
    "a",
    "an",
    "of",
    "in",
    "and",
    "or",
    "to",
    "for",
    "with",
    "at",
    "by",
    "from",
    "on",
    "as",
}

_WANT_TO_READ_QUERY = """
query WantToRead {
  me {
    user_books(where: {status_id: {_eq: 1}}) {
      book { id title contributions { author { name } } }
    }
  }
}
"""

_IN_DOVER_QUERY = """
query InDoverList($slug: String!) {
  me {
    lists(where: {slug: {_eq: $slug}}) {
      list_books {
        book { id title contributions { author { name } } }
      }
    }
  }
}
"""


def _get_token() -> str:
    token = os.environ.get("HARDCOVER_API_KEY", "")
    if not token:
        raise RuntimeError("HARDCOVER_API_KEY not set. Add it to ~/.config/sandy/sandy.toml.")
    return token


def _graphql(query: str, variables: dict | None = None, token: str = "") -> dict:
    resp = requests.post(
        _API_URL,
        json={"query": query, "variables": variables or {}},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()
    if "errors" in result:
        raise RuntimeError(f"GraphQL error: {result['errors']}")
    return result


def _parse_books(user_books_or_list_books: list[dict], key: str) -> list[dict]:
    out = []
    for item in user_books_or_list_books:
        book = item["book"]
        contributions = book.get("contributions", [])
        author = "Unknown"
        if contributions:
            a = contributions[0].get("author")
            if a:
                author = a.get("name", "Unknown")
        out.append({"id": book["id"], "title": book["title"], "author": author})
    return out


def _fetch_want_to_read(token: str) -> list[dict]:
    data = _graphql(_WANT_TO_READ_QUERY, token=token)
    me = data["data"]["me"]
    if not me:
        return []
    return _parse_books(me[0]["user_books"], "book")


def _fetch_in_dover(token: str) -> list[dict]:
    data = _graphql(_IN_DOVER_QUERY, variables={"slug": "in-dover"}, token=token)
    me = data["data"]["me"]
    if not me:
        return []
    lists = me[0]["lists"]
    if not lists:
        return []
    return _parse_books(lists[0]["list_books"], "book")


def _build_search_url(title: str) -> str:
    words = title.split()
    filtered = [w for w in words if w.lower() not in _STOP_WORDS]
    clean = " ".join(filtered) if filtered else title
    return f"{_KOHA_BASE}?q={quote_plus(clean)}{_KOHA_LIMITS}"


def handle(text: str, actor: str) -> dict:
    token = _get_token()
    want_to_read = _fetch_want_to_read(token)
    in_dover = _fetch_in_dover(token)

    want_ids = {b["id"] for b in want_to_read}
    candidates = [b for b in in_dover if b["id"] in want_ids]

    if not candidates:
        no_books_msg = (
            "No books found that are both in your Dover list and on your Want to Read shelf."
        )
        return {"text": no_books_msg}

    book = random.choice(candidates)
    url = _build_search_url(book["title"])
    return {
        "text": f"{book['title']} by {book['author']}",
        "links": [{"label": "Reserve at Dover Library", "url": url}],
    }
