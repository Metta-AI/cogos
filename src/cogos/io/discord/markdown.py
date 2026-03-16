"""Convert standard markdown to Discord-compatible markdown."""
from __future__ import annotations

import re

_HR_LINE = "─" * 20

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_HR_RE = re.compile(r"^---+\s*$", re.MULTILINE)

_TABLE_LINE_RE = re.compile(r"^\|.*\|$")
_TABLE_SEP_RE = re.compile(r"^\|[\s:|-]+\|$")


def convert_markdown(content: str) -> str:
    """Convert standard markdown to Discord-flavored markdown.

    Preserves content inside code blocks (``` ... ```) unchanged.
    Code blocks containing backtick characters may not be detected correctly.
    """
    parts = re.split(r"(```[\s\S]*?```)", content)
    result_parts = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            result_parts.append(part)
        else:
            result_parts.append(_convert_prose(part))
    return "".join(result_parts)


def _convert_prose(text: str) -> str:
    """Convert non-code-block markdown text."""
    text = _convert_tables(text)
    text = _IMAGE_RE.sub(r"\1: <\2>", text)
    text = _LINK_RE.sub(r"\1 (<\2>)", text)
    text = _HEADING_RE.sub(r"**\2**", text)
    text = _HR_RE.sub(_HR_LINE, text)
    return text


def _convert_tables(text: str) -> str:
    """Wrap markdown tables in code blocks."""
    lines = text.split("\n")
    result: list[str] = []
    table_lines: list[str] = []
    in_table = False

    for line in lines:
        is_table_line = bool(_TABLE_LINE_RE.match(line.strip()))
        is_sep_line = bool(_TABLE_SEP_RE.match(line.strip()))

        if is_table_line or is_sep_line:
            if not in_table:
                in_table = True
            table_lines.append(line)
        else:
            if in_table:
                result.append("```\n" + "\n".join(table_lines) + "\n```")
                table_lines = []
                in_table = False
            result.append(line)

    if in_table:
        result.append("```\n" + "\n".join(table_lines) + "\n```")

    return "\n".join(result)
