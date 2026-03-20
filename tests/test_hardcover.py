"""Tests for the hardcover Sandy plugin."""

import pytest

import sandy.plugins.hardcover as hardcover


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_BOOK_1 = {
    "id": 1,
    "title": "The Great Gatsby",
    "contributions": [{"author": {"name": "F. Scott Fitzgerald"}}],
}
_BOOK_2 = {
    "id": 2,
    "title": "To Kill a Mockingbird",
    "contributions": [{"author": {"name": "Harper Lee"}}],
}
_BOOK_3 = {
    "id": 3,
    "title": "Of Mice and Men",
    "contributions": [{"author": {"name": "John Steinbeck"}}],
}


def _want_to_read_response(*books):
    return {"data": {"me": [{"user_books": [{"book": b} for b in books]}]}}


def _in_dover_response(*books):
    return {"data": {"me": [{"lists": [{"list_books": [{"book": b} for b in books]}]}]}}


# ---------------------------------------------------------------------------
# Module attributes
# ---------------------------------------------------------------------------


def test_name():
    assert hardcover.name == "hardcover"


def test_commands():
    assert "library book" in hardcover.commands
    assert "suggest a library book" in hardcover.commands


# ---------------------------------------------------------------------------
# _get_token
# ---------------------------------------------------------------------------


def test_get_token_from_env(monkeypatch):
    monkeypatch.setenv("HARDCOVER_API_KEY", "mytoken")
    assert hardcover._get_token() == "mytoken"


def test_get_token_missing(monkeypatch):
    monkeypatch.delenv("HARDCOVER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="HARDCOVER_API_KEY not set"):
        hardcover._get_token()


# ---------------------------------------------------------------------------
# _author_last_name
# ---------------------------------------------------------------------------


def test_author_last_name_first_last():
    assert hardcover._author_last_name("John Vaillant") == "Vaillant"


def test_author_last_name_last_first():
    assert hardcover._author_last_name("Vaillant, John") == "Vaillant"


def test_author_last_name_single_word():
    assert hardcover._author_last_name("Voltaire") == "Voltaire"


def test_author_last_name_strips_whitespace():
    assert hardcover._author_last_name("  Harper Lee  ") == "Lee"


# ---------------------------------------------------------------------------
# _build_search_url
# ---------------------------------------------------------------------------


def test_build_search_url_strips_stop_words():
    url = hardcover._build_search_url("The Great Gatsby")
    assert "Great+Gatsby" in url
    assert "The" not in url.split("?q=")[1]


def test_build_search_url_includes_author_last_name():
    url = hardcover._build_search_url("The Tiger", "John Vaillant")
    assert "Vaillant" in url
    assert "Tiger" in url


def test_build_search_url_author_last_comma_format():
    url = hardcover._build_search_url("Infinite Jest", "Wallace, David Foster")
    assert "Wallace" in url
    assert "Jest" in url


def test_build_search_url_no_author_omits_unknown():
    url = hardcover._build_search_url("Some Book", "Unknown")
    assert "Unknown" not in url


def test_build_search_url_keeps_all_words_if_all_stop():
    # All stop words → keep original to avoid empty query
    url = hardcover._build_search_url("the a an")
    assert "the+a+an" in url


def test_build_search_url_includes_koha_limits():
    url = hardcover._build_search_url("Test Book")
    assert "limit=itype%3ABK" in url
    assert "limit=branch%3ADOVER" in url


# ---------------------------------------------------------------------------
# _fetch_want_to_read / _fetch_in_dover
# ---------------------------------------------------------------------------


def test_fetch_want_to_read(monkeypatch):
    monkeypatch.setattr(hardcover, "_graphql", lambda *a, **kw: _want_to_read_response(_BOOK_1))
    books = hardcover._fetch_want_to_read("token")
    assert len(books) == 1
    assert books[0]["title"] == "The Great Gatsby"
    assert books[0]["author"] == "F. Scott Fitzgerald"


def test_fetch_want_to_read_empty_me(monkeypatch):
    monkeypatch.setattr(hardcover, "_graphql", lambda *a, **kw: {"data": {"me": []}})
    assert hardcover._fetch_want_to_read("token") == []


def test_fetch_in_dover(monkeypatch):
    monkeypatch.setattr(hardcover, "_graphql", lambda *a, **kw: _in_dover_response(_BOOK_2))
    books = hardcover._fetch_in_dover("token")
    assert len(books) == 1
    assert books[0]["title"] == "To Kill a Mockingbird"


def test_fetch_in_dover_no_lists(monkeypatch):
    monkeypatch.setattr(hardcover, "_graphql", lambda *a, **kw: {"data": {"me": [{"lists": []}]}})
    assert hardcover._fetch_in_dover("token") == []


# ---------------------------------------------------------------------------
# handle
# ---------------------------------------------------------------------------


def test_handle_returns_book_and_url(monkeypatch):
    monkeypatch.setenv("HARDCOVER_API_KEY", "tok")
    call_count = [0]

    def fake_graphql(query, variables=None, token=""):
        call_count[0] += 1
        if "WantToRead" in query:
            return _want_to_read_response(_BOOK_1, _BOOK_2)
        return _in_dover_response(_BOOK_1)

    monkeypatch.setattr(hardcover, "_graphql", fake_graphql)
    result = hardcover.handle("library book", "tom")
    assert "Great Gatsby" in result["text"]
    links = result.get("links", [])
    assert any("Dover" in link.get("label", "") for link in links)
    assert any("https://" in link.get("url", "") for link in links)


def test_handle_no_candidates(monkeypatch):
    monkeypatch.setenv("HARDCOVER_API_KEY", "tok")

    def fake_graphql(query, variables=None, token=""):
        if "WantToRead" in query:
            return _want_to_read_response(_BOOK_1)
        return _in_dover_response(_BOOK_2)  # different book, no intersection

    monkeypatch.setattr(hardcover, "_graphql", fake_graphql)
    result = hardcover.handle("library book", "tom")
    assert "No books found" in result["text"]
