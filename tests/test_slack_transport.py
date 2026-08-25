"""Tests for Slack transport plugin."""

from sandy.transports.slack import format_response, inbound_lag_seconds


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


# --- inbound latency instrumentation (issue #119) ---


def _rich_text_blocks(blocks):
    """Helper: return the rich_text_preformatted text payloads from a block list."""
    out = []
    for b in blocks:
        if b.get("type") != "rich_text":
            continue
        for el in b.get("elements", []):
            if el.get("type") == "rich_text_preformatted":
                out.append("".join(sub.get("text", "") for sub in el.get("elements", [])))
    return out


def test_format_response_code_text_renders_rich_text_preformatted():
    """The code_text field renders as a Slack rich_text_preformatted block (#122)."""
    result = format_response("itguy", {"title": "IT Guy", "code_text": "log line 1\nlog line 2"})
    blocks = result["blocks"]
    code_blocks = _rich_text_blocks(blocks)
    assert code_blocks == ["log line 1\nlog line 2"]
    # The rich_text block is parser-safe — content is not wrapped in markdown fences.
    assert all("```" not in t for t in code_blocks)


def test_format_response_code_text_alongside_text():
    """code_text and text coexist: code first (rich_text), then mrkdwn section."""
    result = format_response(
        "itguy",
        {"code_text": "code body", "text": "human commentary"},
    )
    blocks = result["blocks"]
    code_blocks = _rich_text_blocks(blocks)
    section_texts = [b["text"]["text"] for b in blocks if b.get("type") == "section"]
    assert "code body" in code_blocks
    assert any("human commentary" in t for t in section_texts)


def test_format_response_legacy_fenced_text_auto_promoted():
    """Legacy plugin that wraps text in ``` is auto-promoted to rich_text_preformatted.

    This is the backward-compat path that fixes #122 even for plugins not yet updated.
    """
    legacy = "```\nfoo bar\nbaz\n```"
    result = format_response("legacy", {"title": "Old plugin", "text": legacy})
    blocks = result["blocks"]
    code_blocks = _rich_text_blocks(blocks)
    assert code_blocks == ["foo bar\nbaz"]
    # No raw mrkdwn section with literal backticks left behind.
    sections = [b for b in blocks if b.get("type") == "section"]
    assert not any("```" in b["text"]["text"] for b in sections)


def test_format_response_partial_fenced_text_not_promoted():
    """Text that only opens a fence (e.g. truncated) is left as mrkdwn — promotion
    requires a full ``` ... ``` wrap, not just a stray opener."""
    result = format_response("test", {"text": "```\nincomplete output"})
    blocks = result["blocks"]
    code_blocks = _rich_text_blocks(blocks)
    assert code_blocks == []
    sections = [b for b in blocks if b.get("type") == "section"]
    assert any("incomplete output" in b["text"]["text"] for b in sections)


def test_format_response_inline_fence_in_text_not_promoted():
    """A fence that's not the whole message (e.g. text + fence + more text) is not promoted."""
    mixed = "Heads up:\n```\nstuff\n```\nthat's all"
    result = format_response("test", {"text": mixed})
    code_blocks = _rich_text_blocks(result["blocks"])
    assert code_blocks == []  # mixed content stays as mrkdwn


def test_format_response_code_text_truncated():
    """code_text longer than the cap is truncated, not rejected."""
    long_code = "x" * 20000
    result = format_response("test", {"code_text": long_code})
    code_blocks = _rich_text_blocks(result["blocks"])
    assert len(code_blocks) == 1
    assert len(code_blocks[0]) == 12000


def test_format_response_code_text_empty_skipped():
    """Empty code_text produces no rich_text block (avoids empty Slack payloads)."""
    result = format_response("test", {"code_text": "", "text": "fallback"})
    code_blocks = _rich_text_blocks(result["blocks"])
    assert code_blocks == []
    # text still renders
    sections = [b for b in result["blocks"] if b.get("type") == "section"]
    assert any("fallback" in b["text"]["text"] for b in sections)


def test_inbound_lag_seconds_basic():
    """Lag is now minus the Slack message post time (event 'ts')."""
    event = {"ts": "1000.000000"}
    assert inbound_lag_seconds(event, now=1002.5) == 2.5


def test_inbound_lag_seconds_subsecond():
    """Sub-second lag is preserved (not rounded to int)."""
    event = {"ts": "1000.000000"}
    lag = inbound_lag_seconds(event, now=1000.25)
    assert abs(lag - 0.25) < 1e-9


def test_inbound_lag_seconds_missing_ts():
    """A missing 'ts' yields None rather than raising — never break message handling."""
    assert inbound_lag_seconds({}, now=1000.0) is None


def test_inbound_lag_seconds_unparseable_ts():
    """A non-numeric 'ts' yields None rather than raising."""
    assert inbound_lag_seconds({"ts": "not-a-number"}, now=1000.0) is None


def test_inbound_lag_seconds_negative_clamped_to_zero():
    """Clock skew (event ts ahead of now) clamps to 0, never negative."""
    event = {"ts": "1000.000000"}
    assert inbound_lag_seconds(event, now=999.0) == 0.0
