"""Slack transport plugin for Sandy.

Uses Socket Mode (no public URL needed). Listens for DMs and @mentions,
routes text through Sandy's pipeline, replies with Block Kit formatted messages.
"""

import logging
import os
import re
import time

logger = logging.getLogger(__name__)

name = "slack"


def inbound_lag_seconds(event: dict, now: float) -> float | None:
    """Seconds between Slack posting a message and Sandy receiving it.

    Slack stamps every message event with ``ts`` (epoch-seconds string).
    Comparing it to wall-clock receipt time isolates network/Slack-delivery
    latency from Sandy's own (already sub-second) processing — the missing
    measurement in issue #119.

    Returns None when ``ts`` is absent or unparseable so instrumentation can
    never break message handling. Clock skew is clamped to 0.
    """
    ts = event.get("ts")
    if ts is None:
        return None
    try:
        posted_at = float(ts)
    except (TypeError, ValueError):
        return None
    return max(0.0, now - posted_at)


def _get_tokens() -> tuple[str, str]:
    app_token = os.environ.get("SLACK_APP_TOKEN", "")
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not app_token or not bot_token:
        raise RuntimeError(
            "SLACK_APP_TOKEN and SLACK_BOT_TOKEN must be set. Add them to sandy.toml under [slack]."
        )
    logger.debug("Slack tokens loaded (app=%s..., bot=%s...)", app_token[:12], bot_token[:12])
    return app_token, bot_token


# Matches a string whose entire body is wrapped in mrkdwn triple-backtick fences:
# leading ```, a newline, the payload, a newline, and a trailing ```. The (?s) flag
# lets the payload contain newlines.  Used to auto-promote legacy plugin responses
# that pre-wrap their text in ``` fences — those fences render unreliably in Slack
# (the section.text 3000-char cap can truncate the closing fence, and embedded
# backticks in the payload close the outer fence early). Promoting them to a
# rich_text_preformatted block sidesteps both failure modes (#122).
_FENCED_RE = re.compile(r"(?s)\A```\n(.*)\n```\Z")

# rich_text_preformatted has no documented hard cap, but cap at 12000 to stay well
# under Slack's overall block-payload limits and avoid an API-rejection failure mode.
_CODE_TEXT_CAP = 12000

# Slack rejects a section block whose text exceeds 3000 characters.
_TEXT_CAP = 3000


# Slack treats `&`, `<` and `>` as control characters in every mrkdwn field:
# `<...>` is how mentions, channel references and hyperlinks are encoded, and `&`
# opens an HTML entity. Those three are also the only characters Slack documents
# an escape for — there is no documented escape for `*`, `_` or backtick.
#
# Order matters and is load-bearing: `&` must be replaced first, or the `&` that
# `&lt;` introduces gets escaped a second time into `&amp;lt;`.
_MRKDWN_CONTROL_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"))

# A truncation that lands inside `&amp;` would ship `&am` to Slack, which renders
# as literal `&am`. Every `&` in an escaped payload belongs to an entity, so a
# trailing `&` followed only by letters is always a fragment and never content.
_PARTIAL_ENTITY_RE = re.compile(r"&[a-z]*\Z")


def escape_mrkdwn(text: str) -> str:
    """Neutralise Slack's control characters in plugin-supplied *text*.

    Escapes `&`, `<` and `>` and nothing else. `*`, `_` and backtick are left
    alone deliberately: three plugins — ``help``, ``sports`` and
    ``printer_status`` — emit `*bold*` and `` `code` `` in ``text`` on purpose,
    so a blanket escape would be a visible regression for them, and Slack
    publishes no escape for those characters anyway (#204).

    The half this *does* fix is the half with a failure mode worse than
    cosmetic: an exception or upstream API string containing `<@U12345>`
    otherwise reaches Slack as a real mention.

    Not idempotent, deliberately: text that already contains `&amp;` becomes
    `&amp;amp;` and renders as the literal `&amp;`. No producer does that today
    — every one of them interpolates raw API data — but a future plugin
    scraping HTML would need to unescape before returning.
    """
    for char, entity in _MRKDWN_CONTROL_ESCAPES:
        text = text.replace(char, entity)
    return text


def _escaped_mrkdwn(text: str, cap: int) -> str:
    """Escape *text* for mrkdwn, then truncate to *cap* without splitting an entity.

    Escaping first and capping second is the only safe order. Capping the raw
    text first would let escaping push the payload back over Slack's hard limit
    and get the whole message rejected.
    """
    return _PARTIAL_ENTITY_RE.sub("", escape_mrkdwn(text)[:cap])


def _join_within_cap(lines: list[str], cap: int) -> str:
    """Newline-join every whole line from *lines* that still fits in *cap*.

    Whole lines rather than a character truncation: each line here is a
    complete `<url|label>` sequence, and a cut inside one leaves a dangling
    `<` that swallows the rest of the message.

    Skips over a line that does not fit rather than stopping at it — the order
    is upstream's (Spotify's release order), so stopping would make *which*
    links survive a matter of where the long one happened to land.

    Returns ``""`` when no line fits at all; the caller must then omit the
    block rather than emit an empty one.
    """
    kept: list[str] = []
    used = 0
    for line in lines:
        extra = len(line) + (1 if kept else 0)
        if used + extra > cap:
            continue
        kept.append(line)
        used += extra
    return "\n".join(kept)


def _rich_text_preformatted_block(text: str) -> dict:
    """Render *text* as a Slack rich_text_preformatted block (Slack's first-class code block)."""
    return {
        "type": "rich_text",
        "elements": [
            {
                "type": "rich_text_preformatted",
                "elements": [{"type": "text", "text": text[:_CODE_TEXT_CAP]}],
            }
        ],
    }


def format_response(plugin_name: str, response: dict) -> dict:
    """Translate a content plugin response dict into Slack Block Kit blocks.

    Recognised response keys:
      title, text, code_text, links, image_url.

    ``code_text`` is rendered as a Slack ``rich_text_preformatted`` block — the
    parser-safe equivalent of a Markdown code fence. Prefer this over wrapping
    ``text`` in triple backticks: mrkdwn fences are unreliable for long output
    (truncated closing fence) or content containing backticks (#122).

    Legacy plugins that pre-wrap ``text`` in triple-backtick fences are
    auto-promoted to a ``rich_text_preformatted`` block so the fix lands
    before every plugin is updated.

    **``text`` is a mrkdwn field, and only half of it is escaped for you.**
    ``&``, ``<`` and ``>`` are escaped here (see :func:`escape_mrkdwn`), so a
    plugin cannot accidentally emit a mention or a hyperlink. ``*``, ``_`` and
    backtick are *not*: they are the formatting vocabulary ``help``, ``sports``
    and ``printer_status`` already write on purpose, so a plugin interpolating
    untrusted text into ``text`` owns that half itself — wrap it in
    ``code_text`` if it must survive verbatim (#204).
    """
    logger.debug("Formatting response for plugin '%s': keys=%s", plugin_name, list(response.keys()))
    blocks = []

    # Truthiness, not `"title" in response`: Slack rejects the whole message
    # over a zero-length `plain_text`, so a present-but-empty title has to be
    # dropped rather than rendered (#207).
    if response.get("title"):
        blocks.append(
            {
                "type": "header",
                "text": {"type": "plain_text", "text": response["title"][:150]},
            }
        )

    code_text = response.get("code_text")
    text = response.get("text")

    # Auto-promote legacy responses whose text is entirely wrapped in ``` fences.
    if code_text is None and isinstance(text, str):
        match = _FENCED_RE.match(text)
        if match:
            code_text = match.group(1)
            text = None

    if isinstance(code_text, str) and code_text:
        blocks.append(_rich_text_preformatted_block(code_text))

    if isinstance(text, str):
        # Guard the ESCAPED body, not the raw input: the cap and the
        # partial-entity trim both run before we know the length (#207).
        body = _escaped_mrkdwn(text, _TEXT_CAP)
        if body:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body}})

    if response.get("links"):
        # Labels carry upstream data (Spotify album names, for one) and an
        # unescaped `>` in one ends the link sequence early. The URL half is
        # left alone on purpose: `&` there is a query separator, escaping it
        # would rewrite every OAuth URL Sandy hands out, and `<`/`>` cannot
        # legally appear unescaped in a URI to begin with.
        link_lines = [
            f"<{link['url']}|{escape_mrkdwn(link['label'])}>" for link in response["links"]
        ]
        # Empty when even the first line is over the cap on its own. Slack
        # rejects a zero-length text object, so emitting the block anyway would
        # turn a *risk* of an over-length rejection into a certain one.
        link_text = _join_within_cap(link_lines, _TEXT_CAP)
        if link_text:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": link_text},
                }
            )
        else:
            # Dropping user-facing content, and for `spotify` the links ARE
            # the answer — say so somewhere, or the only symptom is a user
            # asking where they went.
            logger.warning(
                "Dropping links block for '%s': no link line fits the %d-char cap (longest %d)",
                plugin_name,
                _TEXT_CAP,
                max(len(line) for line in link_lines),
            )

    if "image_url" in response:
        blocks.append(
            {
                "type": "image",
                "image_url": response["image_url"],
                # `or`, not a dict default: the default cannot fire when the
                # key is present-but-empty, and `alt_text` is the third
                # zero-length-rejection site on the empty-title path (#207).
                "alt_text": response.get("title") or plugin_name,
            }
        )

    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"via *{plugin_name}*"}],
        }
    )

    return {"blocks": blocks}


async def listen(callback):
    """Start the Slack Socket Mode listener.

    callback signature: async callback(text, actor, reply_fn)
    """
    import asyncio

    from slack_bolt.async_app import AsyncApp
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

    app_token, bot_token = _get_tokens()
    app = AsyncApp(token=bot_token)
    logger.info("Slack app created, registering event handlers")

    # Cache (display_name, tz) per Slack user ID to avoid extra API calls per message.
    _user_info_cache: dict[str, tuple[str, str | None]] = {}

    @app.event("message")
    async def handle_message(event, say):
        received_at = time.time()
        logger.debug("Raw Slack event received: %s", event)
        text = event.get("text", "").strip()
        if not text:
            logger.debug("Empty text in event, ignoring")
            return

        # Strip bot mention if present (e.g., "<@U12345> find me new music")
        if text.startswith("<@"):
            original = text
            text = text.split(">", 1)[-1].strip()
            logger.debug("Stripped mention: '%s' -> '%s'", original, text)

        user_id = event.get("user", "unknown")
        actor = user_id

        lag = inbound_lag_seconds(event, received_at)
        if lag is None:
            logger.info("Message from user=%s: '%s'", actor, text)
        else:
            logger.info(
                "Message from user=%s: '%s' (Slack→Sandy delivery lag %.2fs)", actor, text, lag
            )

        # Fetch display name and timezone from Slack (cached per user ID)
        actor_tz: str | None = None
        if user_id in _user_info_cache:
            actor, actor_tz = _user_info_cache[user_id]
            logger.debug("User info from cache: actor='%s', tz='%s'", actor, actor_tz)
        else:
            try:
                user_info = await app.client.users_info(user=user_id)
                display = (
                    user_info["user"]["profile"].get("display_name") or user_info["user"]["name"]
                )
                actor = display.lower()
                actor_tz = user_info["user"].get("tz")
                _user_info_cache[user_id] = (actor, actor_tz)
                logger.debug("Resolved user info: actor='%s', tz='%s'", actor, actor_tz)
            except Exception as e:
                logger.warning("Could not resolve user info for %s: %s", user_id, e)

        async def reply_fn(plugin_name, response):
            formatted = format_response(plugin_name, response)
            logger.debug("Sending reply for '%s': %d blocks", plugin_name, len(formatted["blocks"]))
            await say(blocks=formatted["blocks"])
            # receipt→reply spans the pipeline AND any uncached users_info call,
            # so it is not pure Sandy compute — label it as the full span.
            elapsed = time.time() - received_at
            logger.info("Reply sent for plugin '%s' (receipt→reply %.2fs)", plugin_name, elapsed)

        await callback(text, actor, reply_fn, tz=actor_tz)

    logger.info("Starting Socket Mode handler")
    handler = AsyncSocketModeHandler(app, app_token)
    try:
        await handler.start_async()
        logger.info("Socket Mode handler started")
    except asyncio.CancelledError:
        logger.info("Socket Mode handler cancelled, closing cleanly")
        await handler.close_async()
        raise
