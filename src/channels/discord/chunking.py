"""Split messages to fit within Discord's 2000-character limit."""

from __future__ import annotations

DISCORD_MAX_LENGTH = 2000


def chunk_message(content: str) -> list[str]:
    """Split content into chunks that fit Discord's message limit.

    Prefers splitting on newlines, then spaces, then hard cuts.
    """
    if not content:
        return []
    if len(content) <= DISCORD_MAX_LENGTH:
        return [content]

    chunks: list[str] = []
    while content:
        if len(content) <= DISCORD_MAX_LENGTH:
            chunks.append(content)
            break

        split_at = content.rfind("\n", 0, DISCORD_MAX_LENGTH)
        if split_at <= 0:
            split_at = content.rfind(" ", 0, DISCORD_MAX_LENGTH)
        if split_at <= 0:
            split_at = DISCORD_MAX_LENGTH

        chunks.append(content[:split_at])
        content = content[split_at:].lstrip("\n")

    return chunks
