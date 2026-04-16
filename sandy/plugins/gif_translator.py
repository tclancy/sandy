"""GIF Translation Bot — generational pop culture translator.

Takes a cultural reference and finds modern equivalents for a target
age group, then fetches GIFs from Giphy to illustrate each suggestion.

Required environment variables (set via [gif_translator] in sandy.toml):
    ANTHROPIC_API_KEY       — Anthropic API key for Claude
    GIPHY_API_KEY           — Giphy API key (free tier)

Optional config (lowercase keys in [gif_translator]):
    default_target_age      — Default target age for translations (default: 28)
    giphy_rating            — Giphy content rating filter (default: pg)
"""

import json
import logging
import os
import re

import anthropic
import requests

logger = logging.getLogger(__name__)

name = "gif_translator"
commands = ["tr8"]

TRANSLATE_SYSTEM_PROMPT = """\
You are a generational pop culture translator. Given a phrase or cultural \
reference, identify what it means (the emotional register, the intent, the \
cultural context) and suggest 3 equivalent references that someone of the \
target age would immediately recognize.

Rules:
- Each suggestion must be a distinct cultural reference (movie, TV show, \
meme, song, viral moment, etc.)
- Include the source and approximate year
- Provide 2-3 Giphy search terms per suggestion that would find a relevant GIF
- If the input is already current for the target age, say so and still \
provide GIF search terms for it
- If the input is obscure or you're unsure, provide broader emotional-register \
matches and note the uncertainty

Return valid JSON only — no markdown, no commentary outside the JSON.\
"""

TRANSLATE_USER_TEMPLATE = """\
Phrase: "{phrase}"

Target audience age: {target_age}

Return a JSON object with this exact structure:
{{
  "original": {{
    "phrase": "the input phrase",
    "source": "where it's from (movie, show, meme, etc.)",
    "year": "approximate year or decade",
    "meaning": "what it means / emotional register in one sentence"
  }},
  "suggestions": [
    {{
      "phrase": "the modern equivalent phrase or reference",
      "source": "where it's from",
      "year": "approximate year",
      "why": "why this is a good equivalent (one sentence)",
      "search_terms": ["giphy search term 1", "giphy search term 2"]
    }}
  ]
}}\
"""

DEFAULT_TARGET_AGE = 28
DEFAULT_GIPHY_RATING = "pg"
GIPHY_SEARCH_URL = "https://api.giphy.com/v1/gifs/search"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
MAX_CLAUDE_TOKENS = 1024


def _parse_args(text: str) -> tuple[str, int]:
    """Extract the phrase and optional --age N from the command text.

    Returns (phrase, target_age).
    """
    default_age = int(os.environ.get("GIF_DEFAULT_TARGET_AGE", str(DEFAULT_TARGET_AGE)))

    cleaned = text.strip()
    for prefix in ("tr8",):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()

    age_match = re.search(r"--age\s+(\d+)", cleaned)
    if age_match:
        target_age = int(age_match.group(1))
        cleaned = cleaned[: age_match.start()] + cleaned[age_match.end() :]
        cleaned = cleaned.strip()
    else:
        target_age = default_age

    return cleaned, target_age


def _translate_reference(phrase: str, target_age: int) -> dict:
    """Call Claude to translate a cultural reference for the target age group."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set. Add it to sandy.toml [gif_translator].")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_CLAUDE_TOKENS,
        system=TRANSLATE_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": TRANSLATE_USER_TEMPLATE.format(
                    phrase=phrase,
                    target_age=target_age,
                ),
            }
        ],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    return json.loads(raw)


def _search_giphy(search_terms: list[str], api_key: str, rating: str) -> dict | None:
    """Search Giphy for the first term that returns a result."""
    for term in search_terms:
        try:
            resp = requests.get(
                GIPHY_SEARCH_URL,
                params={
                    "q": term,
                    "api_key": api_key,
                    "rating": rating,
                    "limit": 1,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if data:
                gif = data[0]
                return {
                    "url": gif.get("url", ""),
                    "image_url": gif.get("images", {}).get("fixed_height", {}).get("url", ""),
                    "title": gif.get("title", ""),
                }
        except (requests.RequestException, KeyError, ValueError):
            logger.debug("Giphy search failed for term: %s", term, exc_info=True)
            continue
    return None


def _format_response(translation: dict, gifs: list[dict | None], target_age: int) -> dict:
    """Build a Sandy response dict from Claude's translation and Giphy results."""
    original = translation.get("original", {})
    suggestions = translation.get("suggestions", [])

    lines = []
    lines.append(
        f'*"{original.get("phrase", "?")}"* — {original.get("source", "unknown")} '
        f"({original.get('year', '?')})"
    )
    lines.append(f"Meaning: {original.get('meaning', 'unknown')}")
    lines.append("")
    lines.append(f"For someone ~{target_age}:")
    lines.append("")

    links = []
    first_gif_url = None

    for i, suggestion in enumerate(suggestions):
        gif = gifs[i] if i < len(gifs) else None
        number = i + 1

        line = f'{number}. *"{suggestion.get("phrase", "?")}"*'
        line += f" — {suggestion.get('source', '?')} ({suggestion.get('year', '?')})"
        lines.append(line)
        lines.append(f"   _{suggestion.get('why', '')}_")

        if gif and gif.get("url"):
            links.append({"label": f"GIF {number}: {gif.get('title', 'View')}", "url": gif["url"]})
            if not first_gif_url and gif.get("image_url"):
                first_gif_url = gif["image_url"]

        lines.append("")

    result: dict = {
        "title": "GIF Translator",
        "text": "\n".join(lines),
    }
    if links:
        result["links"] = links
    if first_gif_url:
        result["image_url"] = first_gif_url

    return result


def _format_text_only(translation: dict, target_age: int) -> dict:
    """Format response when Giphy is unavailable (no API key)."""
    result = _format_response(translation, [], target_age)
    result["text"] += "\n_Giphy API key not configured — showing text suggestions only._"
    return result


def handle(text: str, actor: str, progress=None) -> dict:
    """Translate a cultural reference for a different generation.

    Usage: tr8 <phrase> [--age N]
    """
    phrase, target_age = _parse_args(text)

    if not phrase:
        return {
            "text": "Usage: `tr8 <phrase> [--age N]`\nExample: `tr8 nuke it from orbit --age 25`"
        }

    if progress:
        progress(f'Translating "{phrase}" for age ~{target_age}…')

    try:
        translation = _translate_reference(phrase, target_age)
    except json.JSONDecodeError as e:
        logger.exception("Failed to parse Claude response")
        return {"text": f"Translation failed — Claude returned invalid JSON: {e}"}
    except RuntimeError as e:
        return {"text": str(e)}
    except anthropic.APIError as e:
        logger.exception("Claude API error")
        return {"text": f"Claude API error: {e}"}

    giphy_key = os.environ.get("GIPHY_API_KEY", "")
    if not giphy_key:
        return _format_text_only(translation, target_age)

    rating = os.environ.get("GIF_GIPHY_RATING", DEFAULT_GIPHY_RATING)
    suggestions = translation.get("suggestions", [])
    gifs: list[dict | None] = []

    for i, suggestion in enumerate(suggestions):
        if progress:
            progress(f"Searching Giphy ({i + 1}/{len(suggestions)})…")
        search_terms = suggestion.get("search_terms", [suggestion.get("phrase", "")])
        gif = _search_giphy(search_terms, giphy_key, rating)
        gifs.append(gif)

    return _format_response(translation, gifs, target_age)
