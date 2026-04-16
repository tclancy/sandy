"""Tests for the gif_translator Sandy plugin."""

import json
from unittest.mock import MagicMock, patch

import pytest

from sandy.plugins import gif_translator


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_TRANSLATION = {
    "original": {
        "phrase": "nuke it from orbit",
        "source": "Aliens (1986)",
        "year": "1986",
        "meaning": "Take extreme, decisive action to completely eliminate a problem",
    },
    "suggestions": [
        {
            "phrase": "this is fine",
            "source": "KC Green webcomic",
            "year": "2013",
            "why": "Same resigned acceptance of an overwhelming situation",
            "search_terms": ["this is fine dog fire", "this is fine meme"],
        },
        {
            "phrase": "delete it. delete the whole thing",
            "source": "Brooklyn Nine-Nine / meme culture",
            "year": "2018",
            "why": "Nuclear option energy — just wipe it all out",
            "search_terms": ["delete everything", "burn it down meme"],
        },
        {
            "phrase": "yeet it into the sun",
            "source": "internet slang / meme",
            "year": "2020",
            "why": "Forceful disposal with maximum enthusiasm",
            "search_terms": ["yeet meme", "throw it away"],
        },
    ],
}

SAMPLE_GIPHY_RESPONSE = {
    "data": [
        {
            "url": "https://giphy.com/gifs/abc123",
            "title": "This Is Fine",
            "images": {
                "fixed_height": {
                    "url": "https://media.giphy.com/media/abc123/200.gif",
                }
            },
        }
    ]
}

EMPTY_GIPHY_RESPONSE = {"data": []}


# ---------------------------------------------------------------------------
# Module-level attribute tests
# ---------------------------------------------------------------------------


def test_name():
    assert gif_translator.name == "gif_translator"


def test_commands():
    assert "tr8" in gif_translator.commands


# ---------------------------------------------------------------------------
# _parse_args
# ---------------------------------------------------------------------------


def test_parse_args_simple_phrase():
    phrase, age = gif_translator._parse_args("tr8 nuke it from orbit")
    assert phrase == "nuke it from orbit"
    assert age == gif_translator.DEFAULT_TARGET_AGE


def test_parse_args_with_age():
    phrase, age = gif_translator._parse_args("tr8 nuke it from orbit --age 22")
    assert phrase == "nuke it from orbit"
    assert age == 22


def test_parse_args_age_at_start():
    phrase, age = gif_translator._parse_args("tr8 --age 35 nuke it from orbit")
    assert phrase == "nuke it from orbit"
    assert age == 35


def test_parse_args_empty():
    phrase, age = gif_translator._parse_args("tr8")
    assert phrase == ""
    assert age == gif_translator.DEFAULT_TARGET_AGE


def test_parse_args_case_insensitive_prefix():
    phrase, age = gif_translator._parse_args("TR8 hello world")
    assert phrase == "hello world"


def test_parse_args_env_default_age(monkeypatch):
    monkeypatch.setenv("GIF_DEFAULT_TARGET_AGE", "35")
    phrase, age = gif_translator._parse_args("tr8 hello")
    assert age == 35


# ---------------------------------------------------------------------------
# _translate_reference
# ---------------------------------------------------------------------------


def _mock_claude_response(content: dict) -> MagicMock:
    """Build a mock Anthropic message response."""
    msg = MagicMock()
    text_block = MagicMock()
    text_block.text = json.dumps(content)
    msg.content = [text_block]
    return msg


@patch("sandy.plugins.gif_translator.anthropic.Anthropic")
def test_translate_reference_success(mock_anthropic_cls, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _mock_claude_response(SAMPLE_TRANSLATION)

    result = gif_translator._translate_reference("nuke it from orbit", 28)

    assert result["original"]["phrase"] == "nuke it from orbit"
    assert len(result["suggestions"]) == 3
    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["model"] == gif_translator.CLAUDE_MODEL
    assert "nuke it from orbit" in call_kwargs["messages"][0]["content"]


@patch("sandy.plugins.gif_translator.anthropic.Anthropic")
def test_translate_reference_strips_markdown_fences(mock_anthropic_cls, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    msg = MagicMock()
    text_block = MagicMock()
    text_block.text = "```json\n" + json.dumps(SAMPLE_TRANSLATION) + "\n```"
    msg.content = [text_block]
    mock_client.messages.create.return_value = msg

    result = gif_translator._translate_reference("test", 28)
    assert result["original"]["phrase"] == "nuke it from orbit"


def test_translate_reference_missing_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY not set"):
        gif_translator._translate_reference("test", 28)


# ---------------------------------------------------------------------------
# _search_giphy
# ---------------------------------------------------------------------------


@patch("sandy.plugins.gif_translator.requests.get")
def test_search_giphy_returns_first_match(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = SAMPLE_GIPHY_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = gif_translator._search_giphy(["this is fine"], "test-key", "pg")

    assert result is not None
    assert result["url"] == "https://giphy.com/gifs/abc123"
    assert "media.giphy.com" in result["image_url"]
    mock_get.assert_called_once()


@patch("sandy.plugins.gif_translator.requests.get")
def test_search_giphy_tries_multiple_terms(mock_get):
    empty_resp = MagicMock()
    empty_resp.json.return_value = EMPTY_GIPHY_RESPONSE
    empty_resp.raise_for_status = MagicMock()

    success_resp = MagicMock()
    success_resp.json.return_value = SAMPLE_GIPHY_RESPONSE
    success_resp.raise_for_status = MagicMock()

    mock_get.side_effect = [empty_resp, success_resp]

    result = gif_translator._search_giphy(["bad term", "good term"], "test-key", "pg")
    assert result is not None
    assert mock_get.call_count == 2


@patch("sandy.plugins.gif_translator.requests.get")
def test_search_giphy_returns_none_on_all_empty(mock_get):
    empty_resp = MagicMock()
    empty_resp.json.return_value = EMPTY_GIPHY_RESPONSE
    empty_resp.raise_for_status = MagicMock()
    mock_get.return_value = empty_resp

    result = gif_translator._search_giphy(["bad1", "bad2"], "test-key", "pg")
    assert result is None


@patch("sandy.plugins.gif_translator.requests.get")
def test_search_giphy_handles_network_error(mock_get):
    import requests

    mock_get.side_effect = requests.ConnectionError("timeout")

    result = gif_translator._search_giphy(["test"], "test-key", "pg")
    assert result is None


# ---------------------------------------------------------------------------
# _format_response
# ---------------------------------------------------------------------------


def test_format_response_with_gifs():
    gifs = [
        {
            "url": "https://giphy.com/1",
            "image_url": "https://media.giphy.com/1.gif",
            "title": "GIF 1",
        },
        {
            "url": "https://giphy.com/2",
            "image_url": "https://media.giphy.com/2.gif",
            "title": "GIF 2",
        },
        None,
    ]

    result = gif_translator._format_response(SAMPLE_TRANSLATION, gifs, 28)

    assert result["title"] == "GIF Translator"
    assert "nuke it from orbit" in result["text"]
    assert "this is fine" in result["text"]
    assert "For someone ~28" in result["text"]
    assert len(result["links"]) == 2
    assert result["image_url"] == "https://media.giphy.com/1.gif"


def test_format_response_no_gifs():
    result = gif_translator._format_response(SAMPLE_TRANSLATION, [], 25)

    assert result["title"] == "GIF Translator"
    assert "For someone ~25" in result["text"]
    assert "links" not in result
    assert "image_url" not in result


def test_format_text_only():
    result = gif_translator._format_text_only(SAMPLE_TRANSLATION, 28)

    assert "Giphy API key not configured" in result["text"]
    assert "nuke it from orbit" in result["text"]


# ---------------------------------------------------------------------------
# handle (integration-level with mocks)
# ---------------------------------------------------------------------------


def test_handle_empty_phrase():
    result = gif_translator.handle("tr8", "tom")
    assert "Usage" in result["text"]


@patch("sandy.plugins.gif_translator._search_giphy")
@patch("sandy.plugins.gif_translator._translate_reference")
def test_handle_full_flow_with_giphy(mock_translate, mock_giphy, monkeypatch):
    monkeypatch.setenv("GIPHY_API_KEY", "test-giphy-key")
    mock_translate.return_value = SAMPLE_TRANSLATION
    mock_giphy.return_value = {
        "url": "https://giphy.com/gif1",
        "image_url": "https://media.giphy.com/gif1.gif",
        "title": "A GIF",
    }

    result = gif_translator.handle("tr8 nuke it from orbit", "tom")

    assert result["title"] == "GIF Translator"
    assert "nuke it from orbit" in result["text"]
    assert result.get("image_url")
    assert result.get("links")
    mock_translate.assert_called_once_with("nuke it from orbit", 28)
    assert mock_giphy.call_count == 3


@patch("sandy.plugins.gif_translator._translate_reference")
def test_handle_without_giphy_key(mock_translate, monkeypatch):
    monkeypatch.delenv("GIPHY_API_KEY", raising=False)
    mock_translate.return_value = SAMPLE_TRANSLATION

    result = gif_translator.handle("tr8 nuke it from orbit", "tom")

    assert "Giphy API key not configured" in result["text"]
    assert "nuke it from orbit" in result["text"]


@patch("sandy.plugins.gif_translator._translate_reference")
def test_handle_with_age_override(mock_translate, monkeypatch):
    monkeypatch.delenv("GIPHY_API_KEY", raising=False)
    mock_translate.return_value = SAMPLE_TRANSLATION

    gif_translator.handle("tr8 nuke it from orbit --age 22", "tom")

    mock_translate.assert_called_once_with("nuke it from orbit", 22)


@patch("sandy.plugins.gif_translator._translate_reference")
def test_handle_claude_api_error(mock_translate, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from anthropic import APIError

    mock_translate.side_effect = APIError(
        message="rate limited",
        request=MagicMock(),
        body=None,
    )

    result = gif_translator.handle("tr8 test phrase", "tom")
    assert "Claude API error" in result["text"]


def test_handle_missing_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = gif_translator.handle("tr8 test phrase", "tom")
    assert "ANTHROPIC_API_KEY not set" in result["text"]


@patch("sandy.plugins.gif_translator._translate_reference")
def test_handle_invalid_json_from_claude(mock_translate, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_translate.side_effect = json.JSONDecodeError("bad json", "", 0)

    result = gif_translator.handle("tr8 test phrase", "tom")
    assert "invalid JSON" in result["text"]


@patch("sandy.plugins.gif_translator._search_giphy")
@patch("sandy.plugins.gif_translator._translate_reference")
def test_handle_progress_callback(mock_translate, mock_giphy, monkeypatch):
    monkeypatch.setenv("GIPHY_API_KEY", "test-giphy-key")
    mock_translate.return_value = SAMPLE_TRANSLATION
    mock_giphy.return_value = None

    messages = []
    gif_translator.handle("tr8 test phrase", "tom", progress=messages.append)

    assert any("Translating" in m for m in messages)
    assert any("Giphy" in m for m in messages)


@patch("sandy.plugins.gif_translator._search_giphy")
@patch("sandy.plugins.gif_translator._translate_reference")
def test_handle_partial_giphy_results(mock_translate, mock_giphy, monkeypatch):
    monkeypatch.setenv("GIPHY_API_KEY", "test-giphy-key")
    mock_translate.return_value = SAMPLE_TRANSLATION
    mock_giphy.side_effect = [
        {
            "url": "https://giphy.com/1",
            "image_url": "https://media.giphy.com/1.gif",
            "title": "Hit",
        },
        None,
        None,
    ]

    result = gif_translator.handle("tr8 nuke it from orbit", "tom")

    assert len(result.get("links", [])) == 1
    assert result.get("image_url")
