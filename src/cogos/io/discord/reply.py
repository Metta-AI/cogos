"""SQS reply queue helpers for sending Discord messages from the cogtainer/executor.

Usage:
    await queue_reply(channel="123", content="Hello!", cogent_name="alpha")
    await queue_reaction(channel="123", message_id="456", emoji="👍", cogent_name="alpha")
    await queue_thread_create(channel="123", thread_name="Topic", cogent_name="alpha")
    await queue_dm(user_id="789", content="Hi!", cogent_name="alpha")
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)


def _get_queue_url(runtime, cogent_name: str) -> str:
    override = os.environ.get("DISCORD_REPLY_QUEUE_URL")
    if override:
        return override
    safe_name = cogent_name.replace(".", "-")
    queue_name = f"cogent-{safe_name}-discord-replies"
    return runtime.get_queue_url(queue_name)


def _send(queue_url: str, body: dict, *, runtime) -> None:
    """Queue a reply message via the runtime."""
    import json as _json
    queue_name = os.environ.get("DISCORD_REPLIES_QUEUE", "cogent-polis-discord-replies")
    # Extract queue name from URL if we have a full URL, otherwise use the URL directly
    runtime.send_queue_message(queue_name, _json.dumps(body))


async def queue_reply(
    channel: str,
    content: str = "",
    *,
    files: list[dict] | None = None,
    thread_id: str | None = None,
    reply_to: str | None = None,
    cogent_name: str | None = None,
    region: str | None = None,
    runtime=None,
) -> None:
    name = cogent_name or os.environ["COGENT_NAME"]
    if runtime is None:
        from cogtainer.runtime.factory import create_executor_runtime
        runtime = create_executor_runtime()
    url = _get_queue_url(runtime, name)
    body: dict = {"channel": channel, "content": content}
    if files:
        body["files"] = files
    if thread_id:
        body["thread_id"] = thread_id
    if reply_to:
        body["reply_to"] = reply_to
    _send(url, body, runtime=runtime)
    logger.debug("Queued reply to channel %s (%d chars)", channel, len(content))


async def queue_reaction(
    channel: str,
    message_id: str,
    emoji: str,
    *,
    cogent_name: str | None = None,
    region: str | None = None,
    runtime=None,
) -> None:
    name = cogent_name or os.environ["COGENT_NAME"]
    if runtime is None:
        from cogtainer.runtime.factory import create_executor_runtime
        runtime = create_executor_runtime()
    url = _get_queue_url(runtime, name)
    body = {"type": "reaction", "channel": channel, "message_id": message_id, "emoji": emoji}
    _send(url, body, runtime=runtime)
    logger.debug("Queued reaction %s on message %s", emoji, message_id)


async def queue_thread_create(
    channel: str,
    thread_name: str,
    content: str = "",
    *,
    message_id: str | None = None,
    cogent_name: str | None = None,
    region: str | None = None,
    runtime=None,
) -> None:
    name = cogent_name or os.environ["COGENT_NAME"]
    if runtime is None:
        from cogtainer.runtime.factory import create_executor_runtime
        runtime = create_executor_runtime()
    url = _get_queue_url(runtime, name)
    body: dict = {"type": "thread_create", "channel": channel, "thread_name": thread_name}
    if content:
        body["content"] = content
    if message_id:
        body["message_id"] = message_id
    _send(url, body, runtime=runtime)
    logger.debug("Queued thread '%s' on channel %s", thread_name, channel)


async def queue_dm(
    user_id: str,
    content: str,
    *,
    cogent_name: str | None = None,
    region: str | None = None,
    runtime=None,
) -> None:
    name = cogent_name or os.environ["COGENT_NAME"]
    if runtime is None:
        from cogtainer.runtime.factory import create_executor_runtime
        runtime = create_executor_runtime()
    url = _get_queue_url(runtime, name)
    body = {"type": "dm", "user_id": user_id, "content": content}
    _send(url, body, runtime=runtime)
    logger.debug("Queued DM to user %s", user_id)
