"""Slack transport plugin for Sandy.

Uses Socket Mode (no public URL needed). Listens for DMs and @mentions,
routes text through Sandy's pipeline, replies with Block Kit formatted messages.
"""

import os

name = "slack"


def _get_tokens() -> tuple[str, str]:
    app_token = os.environ.get("SLACK_APP_TOKEN", "")
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not app_token or not bot_token:
        raise RuntimeError(
            "SLACK_APP_TOKEN and SLACK_BOT_TOKEN must be set. Add them to sandy.toml under [slack]."
        )
    return app_token, bot_token


def format_response(plugin_name: str, response: dict) -> dict:
    """Translate a content plugin response dict into Slack Block Kit blocks."""
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
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

    app_token, bot_token = _get_tokens()
    app = AsyncApp(token=bot_token)

    @app.event("message")
    async def handle_message(event, say):
        text = event.get("text", "").strip()
        if not text:
            return

        # Strip bot mention if present (e.g., "<@U12345> find me new music")
        if text.startswith("<@"):
            text = text.split(">", 1)[-1].strip()

        actor = event.get("user", "unknown")

        # Try to get display name for actor
        try:
            user_info = await app.client.users_info(user=actor)
            actor = user_info["user"]["profile"].get("display_name") or user_info["user"]["name"]
            actor = actor.lower()
        except Exception:
            pass

        async def reply_fn(plugin_name, response):
            formatted = format_response(plugin_name, response)
            await say(blocks=formatted["blocks"])

        await callback(text, actor, reply_fn)

    handler = AsyncSocketModeHandler(app, app_token)
    await handler.start_async()
