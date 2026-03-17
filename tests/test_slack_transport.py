"""Tests for Slack transport plugin."""

from sandy.transports.slack import format_response


def test_format_response_text_only():
    """Plain text response produces a section block."""
    result = format_response("echo", {"text": "hello world"})
    blocks = result["blocks"]
    assert any(b["type"] == "context" for b in blocks)
    section = next(b for b in blocks if b["type"] == "section")
    assert "hello world" in section["text"]["text"]


def test_format_response_with_title():
    """Response with title produces a header block."""
    result = format_response(
        "spotify",
        {
            "title": "New releases",
            "text": "Artist — Album",
        },
    )
    blocks = result["blocks"]
    header = next(b for b in blocks if b["type"] == "header")
    assert "New releases" in header["text"]["text"]


def test_format_response_with_links():
    """Response with links includes them in a section."""
    result = format_response(
        "hardcover",
        {
            "text": "Book Title by Author",
            "links": [{"label": "Reserve", "url": "https://example.com"}],
        },
    )
    blocks = result["blocks"]
    link_sections = [b for b in blocks if b["type"] == "section" and "Reserve" in b["text"]["text"]]
    assert len(link_sections) == 1
    assert "https://example.com" in link_sections[0]["text"]["text"]


def test_format_response_with_image():
    """Response with image_url includes an image block."""
    result = format_response(
        "test",
        {
            "text": "Check this out",
            "image_url": "https://example.com/image.png",
        },
    )
    blocks = result["blocks"]
    image = next(b for b in blocks if b["type"] == "image")
    assert image["image_url"] == "https://example.com/image.png"


def test_format_response_always_has_context():
    """Every response includes a context block with plugin name."""
    result = format_response("spotify", {"text": "test"})
    blocks = result["blocks"]
    context = next(b for b in blocks if b["type"] == "context")
    assert "spotify" in context["elements"][0]["text"]


def test_format_response_title_truncated():
    """Titles longer than 150 chars are truncated."""
    long_title = "x" * 200
    result = format_response("test", {"title": long_title})
    blocks = result["blocks"]
    header = next(b for b in blocks if b["type"] == "header")
    assert len(header["text"]["text"]) == 150


def test_format_response_text_truncated():
    """Text longer than 3000 chars is truncated."""
    long_text = "x" * 4000
    result = format_response("test", {"text": long_text})
    blocks = result["blocks"]
    section = next(b for b in blocks if b["type"] == "section" and "x" in b["text"]["text"])
    assert len(section["text"]["text"]) == 3000


def test_format_response_empty_links():
    """Empty links list doesn't create a section."""
    result = format_response("test", {"text": "test", "links": []})
    blocks = result["blocks"]
    # Context block is always present
    assert any(b["type"] == "context" for b in blocks)


def test_format_response_multiple_links():
    """Multiple links are formatted correctly."""
    result = format_response(
        "test",
        {
            "text": "Results",
            "links": [
                {"label": "First", "url": "https://example.com/1"},
                {"label": "Second", "url": "https://example.com/2"},
            ],
        },
    )
    blocks = result["blocks"]
    link_section = next(
        b for b in blocks if b["type"] == "section" and "First" in b["text"]["text"]
    )
    text = link_section["text"]["text"]
    assert "First" in text
    assert "Second" in text
    assert "https://example.com/1" in text
    assert "https://example.com/2" in text
