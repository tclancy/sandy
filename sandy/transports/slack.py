"""Slack transport plugin for Sandy.

Uses Socket Mode (no public URL needed). Listens for DMs and @mentions,
routes text through Sandy's pipeline, replies with Block Kit formatted messages.
"""

import logging
import os

logger = logging.getLogger(__name__)

name = "slack"


def _get_tokens() -> tuple[str, str]:
    app_token = os.environ.get("SLACK_APP_TOKEN", "")
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not app_token or not bot_token:
        raise RuntimeError(
            "SLACK_APP_TOKEN and SLACK_BOT_TOKEN must be set. Add them to sandy.toml under [slack]."
        )
    logger.debug("Slack tokens loaded (app=%s..., bot=%s...)", app_token[:12], bot_token[:12])
    return app_token, bot_token


def format_response(plugin_name: str, response: dict) -> dict:
    """Translate a content plugin response dict into Slack Block Kit blocks."""
    logger.debug("Formatting response for plugin '%s': keys=%s", plugin_name, list(response.keys()))
    blocks = []

    if "title" in response:
        blocks.append(
            {
                "type": "header",
                "text": {"type": "plain_text", "text": response["title"][:150]},
            }
        )

    if "text" in response:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": response["text"][:3000]},
            }
        )

    if response.get("links"):
        link_lines = [f"<{link['url']}|{link['label']}>" for link in response["links"]]
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(link_lines)},
            }
        )

    if "image_url" in response:
        blocks.append(
            {
                "type": "image",
                "image_url": response["image_url"],
                "alt_text": response.get("title", plugin_name),
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
        logger.info("Message from user=%s: '%s'", actor, text)

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
            logger.info("Reply sent for plugin '%s'", plugin_name)

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
