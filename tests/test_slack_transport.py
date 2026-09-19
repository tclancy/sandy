"""Tests for Slack transport plugin."""

from sandy.transports.slack import escape_mrkdwn, format_response, inbound_lag_seconds


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
    legacy = "```\nfoo <bar>\nbaz\n```"
    result = format_response("legacy", {"title": "Old plugin", "text": legacy})
    blocks = result["blocks"]
    code_blocks = _rich_text_blocks(blocks)
    # Promoted to rich_text_preformatted, which is literal — so NOT escaped,
    # even though the same bytes arriving as an unpromoted `text` would be.
    assert code_blocks == ["foo <bar>\nbaz"]
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


# --- mrkdwn control-character escaping (issue #204) ---
#
# Slack interprets `&`, `<` and `>` as control characters in every mrkdwn field.
# `*`, `_` and backtick are deliberately NOT escaped: three plugins (help,
# sports, printer_status) emit them on purpose, and Slack documents no escape
# for them. See `escape_mrkdwn`'s docstring for the measurement behind that.


def _section_text(result, needle):
    """Return the first section block's mrkdwn text containing *needle*."""
    return next(
        b["text"]["text"]
        for b in result["blocks"]
        if b["type"] == "section" and needle in b["text"]["text"]
    )


def test_escape_mrkdwn_neutralises_a_user_mention():
    """`<@U12345>` must not reach Slack as a real mention."""
    assert escape_mrkdwn("no config for <@U12345>") == "no config for &lt;@U12345&gt;"


def test_escape_mrkdwn_escapes_ampersand_before_angle_brackets():
    """`<` becomes `&lt;`, never `&amp;lt;` — the `&` pass must run first."""
    assert escape_mrkdwn("<") == "&lt;"
    assert escape_mrkdwn(">") == "&gt;"


def test_escape_mrkdwn_escapes_a_literal_ampersand():
    assert escape_mrkdwn("Tom & Jerry") == "Tom &amp; Jerry"


def test_escape_mrkdwn_leaves_deliberate_markup_alone():
    """help/sports/printer_status emit `*bold*` and `code` on purpose."""
    assert escape_mrkdwn("*Everton* (FT): `lpstat -p` _x_") == "*Everton* (FT): `lpstat -p` _x_"


def test_format_response_escapes_control_chars_in_text():
    """An exception string reaching `text` renders literally, not as a mention."""
    result = format_response("dispatch", {"text": "failed: <@U12345> & <Foo object at 0x1>"})
    text = _section_text(result, "failed:")
    assert text == "failed: &lt;@U12345&gt; &amp; &lt;Foo object at 0x1&gt;"


def test_format_response_preserves_deliberate_mrkdwn_in_text():
    """Escaping must not regress the three plugins that format on purpose."""
    result = format_response("sports", {"text": "*Today's Results:*\n*Everton* (FT): 2-1"})
    text = _section_text(result, "Everton")
    assert text == "*Today's Results:*\n*Everton* (FT): 2-1"


def test_format_response_does_not_escape_code_text():
    """rich_text_preformatted is literal — escaping there would show `&amp;`."""
    result = format_response("test", {"code_text": "if a < b && c > d:"})
    block = next(b for b in result["blocks"] if b["type"] == "rich_text")
    assert block["elements"][0]["elements"][0]["text"] == "if a < b && c > d:"


def test_format_response_escapes_link_labels():
    """A `>` in an upstream label must not end the link sequence early.

    `|` is deliberately not escaped: Slack splits on the *first* pipe, so a
    later one is ordinary label text.
    """
    result = format_response(
        "spotify",
        {"links": [{"label": "A|B <redacted>", "url": "https://example.com/?a=1&b=2"}]},
    )
    text = _section_text(result, "example.com")
    assert text == "<https://example.com/?a=1&b=2|A|B &lt;redacted&gt;>"


def test_format_response_leaves_link_urls_alone():
    """The URL half is not escaped — `&` there is a query separator, not markup.

    Escaping it would rewrite every OAuth URL Sandy hands out (the Spotify
    `music login` link carries `scope`, `state` and `redirect_uri`), and buys
    nothing: `<` and `>` cannot legally appear unescaped in a URI anyway.
    """
    url = "https://accounts.spotify.com/authorize?scope=a&state=b&redirect_uri=c"
    result = format_response("music_discovery", {"links": [{"label": "Log in", "url": url}]})
    assert _section_text(result, "accounts.spotify") == f"<{url}|Log in>"


def test_format_response_drops_whole_link_lines_over_the_cap():
    """The links section is capped too — and by whole lines, not mid-sequence.

    A section over 3000 characters gets the entire message rejected by Slack.
    Cutting mid-`<url|label>` would instead leave a dangling `<`.
    """
    links = [{"label": "L" * 100, "url": "https://example.com/" + "u" * 100} for _ in range(40)]
    text = _section_text(format_response("spotify", {"links": links}), "example.com")
    assert len(text) <= 3000
    assert text.endswith(">")
    assert all(line.startswith("<") and line.endswith(">") for line in text.split("\n"))


def test_format_response_truncates_after_escaping():
    """The 3000-char Slack cap applies to the escaped payload, not the raw one."""
    result = format_response("test", {"text": "&" * 2000})
    text = _section_text(result, "&amp;")
    assert len(text) <= 3000


def test_format_response_never_emits_a_half_written_entity():
    """Truncation that lands mid-entity must drop the fragment, not ship `&a`.

    2998 filler chars plus one `&` escapes to 3003; the cut at 3000 lands two
    characters into the `&amp;`. An entity-aligned payload cannot show this —
    `&amp;` is 5 chars and 3000 divides by 5, so every straddle test has to be
    built out of a deliberately unaligned prefix.
    """
    result = format_response("test", {"text": "x" * 2998 + "&"})
    text = _section_text(result, "x")
    assert text == "x" * 2998


def test_dispatch_placeholder_syntax_is_escaped_end_to_end():
    """The other half of #204's split, on the producers it actually changes.

    Four plugins write `<placeholder>` into `text` — `dispatch` (twice),
    `cast_to_tv` and `music_discovery`. None is a Slack control sequence, so
    Slack renders them literally today; after this change they arrive as
    entities and Slack decodes them back. This is the test that goes red if
    anyone narrows the escape to "only real control sequences".
    """
    from sandy.plugins.dispatch import _SHIFT_HELP

    text = _section_text(format_response("dispatch", {"text": _SHIFT_HELP}), "dispatch shift")
    assert text.startswith("`dispatch shift &lt;kind&gt;` runs a Dispatch shift on the Mac.")


def test_sports_bold_survives_the_transport_end_to_end():
    """The decision in #204 is that three plugins own `*` — pin one of them.

    A blanket escape of `text` passes every unit test above and still breaks
    this: `sports` builds its whole layout out of mrkdwn bold.
    """
    from sandy.plugins.sports import _build_response

    response = _build_response(
        [{"team": "Everton", "game": "EVE vs LIV", "status": "FT", "score": "2-1"}],
        [],
    )
    text = _section_text(format_response("sports", response), "Everton")
    assert "*Everton* (FT): EVE vs LIV — 2-1" in text
    # Every `*` is intact; the section header's literal `&` is entity-escaped,
    # which Slack decodes back to `&` on render.
    assert text.startswith("*Today's Results &amp; Live Scores:*\n")
    assert text.count("*") == response["text"].count("*")


def test_format_response_omits_the_links_block_when_nothing_fits():
    """A single over-cap link must drop the block, not emit an empty one.

    Slack's Block Kit rejects a `text` object of zero length outright, so
    returning "" here would turn a risk of an over-length rejection into a
    guaranteed one — strictly worse than the uncapped code it replaced.
    """
    result = format_response(
        "spotify", {"text": "ok", "links": [{"label": "L" * 4000, "url": "https://example.com"}]}
    )
    assert not any("example.com" in b.get("text", {}).get("text", "") for b in result["blocks"])
    assert all(b["text"]["text"] for b in result["blocks"] if b["type"] == "section"), (
        "no section may carry empty text"
    )
