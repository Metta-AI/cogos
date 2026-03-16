"""Split messages to fit within Discord's 2000-character limit.

Markdown-aware: preserves code blocks, prefers splitting on blank lines.
"""
from __future__ import annotations

import re

DISCORD_MAX_LENGTH = 2000


def chunk_message(content: str) -> list[str]:
    """Split content into chunks that fit Discord's message limit.

    Rules:
    1. Never split inside a code block if it fits in one chunk.
    2. If a code block exceeds the limit, split it with close/reopen fences.
    3. Prefer splitting on: blank lines > newlines > spaces > hard cuts.
    """
    if not content:
        return []
    if len(content) <= DISCORD_MAX_LENGTH:
        return [content]

    segments = _split_into_segments(content)

    chunks: list[str] = []
    current = ""

    for segment in segments:
        if segment["type"] == "code" and len(segment["text"]) > DISCORD_MAX_LENGTH:
            if current.strip():
                chunks.extend(_chunk_prose(current))
                current = ""
            chunks.extend(_split_code_block(segment["text"], segment["lang"]))
        elif len(current) + len(segment["text"]) <= DISCORD_MAX_LENGTH:
            current += segment["text"]
        else:
            if current.strip():
                chunks.extend(_chunk_prose(current))
            current = segment["text"]

    if current.strip():
        chunks.extend(_chunk_prose(current))

    return chunks


def _split_into_segments(content: str) -> list[dict]:
    """Split content into alternating prose and code block segments."""
    segments: list[dict] = []
    parts = re.split(r"(```\w*\n.*?```)", content, flags=re.DOTALL)

    for part in parts:
        if part.startswith("```") and part.rstrip().endswith("```"):
            first_line = part.split("\n", 1)[0]
            lang = first_line[3:].strip()
            segments.append({"type": "code", "text": part, "lang": lang})
        else:
            segments.append({"type": "prose", "text": part, "lang": ""})

    return segments


def _chunk_prose(text: str) -> list[str]:
    """Split prose text respecting the character limit."""
    if not text.strip():
        return []
    if len(text) <= DISCORD_MAX_LENGTH:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= DISCORD_MAX_LENGTH:
            chunks.append(text)
            break

        split_at = text.rfind("\n\n", 0, DISCORD_MAX_LENGTH)
        if split_at > 0:
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
            continue

        split_at = text.rfind("\n", 0, DISCORD_MAX_LENGTH)
        if split_at > 0:
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
            continue

        split_at = text.rfind(" ", 0, DISCORD_MAX_LENGTH)
        if split_at > 0:
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip()
            continue

        chunks.append(text[:DISCORD_MAX_LENGTH])
        text = text[DISCORD_MAX_LENGTH:]

    return chunks


def _split_code_block(code: str, lang: str) -> list[str]:
    """Split an oversized code block into multiple valid code blocks."""
    lines = code.split("\n")
    inner_lines = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]

    fence_open = f"```{lang}\n" if lang else "```\n"
    fence_close = "\n```"
    overhead = len(fence_open) + len(fence_close)
    max_inner = DISCORD_MAX_LENGTH - overhead

    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for line in inner_lines:
        line_len = len(line) + 1
        if current_len + line_len > max_inner and current_lines:
            chunks.append(fence_open + "\n".join(current_lines) + fence_close)
            current_lines = []
            current_len = 0
        current_lines.append(line)
        current_len += line_len

    if current_lines:
        chunks.append(fence_open + "\n".join(current_lines) + fence_close)

    return chunks
