"""Tests for Discord message chunking."""

from cogos.io.discord.chunking import chunk_message, DISCORD_MAX_LENGTH


class TestChunkMessage:
    def test_empty_returns_empty(self):
        assert chunk_message("") == []

    def test_short_message_unchanged(self):
        assert chunk_message("hello") == ["hello"]

    def test_exact_limit_unchanged(self):
        msg = "a" * DISCORD_MAX_LENGTH
        assert chunk_message(msg) == [msg]

    def test_splits_on_newline(self):
        part1 = "a" * 1500
        part2 = "b" * 1500
        msg = part1 + "\n" + part2
        chunks = chunk_message(msg)
        assert len(chunks) == 2
        assert chunks[0] == part1
        assert chunks[1] == part2

    def test_splits_on_space_when_no_newline(self):
        part1 = "a" * 1500
        part2 = "b" * 1500
        msg = part1 + " " + part2
        chunks = chunk_message(msg)
        assert len(chunks) == 2
        assert chunks[0] == part1

    def test_hard_split_when_no_whitespace(self):
        msg = "a" * 4500
        chunks = chunk_message(msg)
        assert len(chunks) == 3
        assert chunks[0] == "a" * DISCORD_MAX_LENGTH
        assert chunks[1] == "a" * DISCORD_MAX_LENGTH
        assert chunks[2] == "a" * 500

    def test_strips_leading_newlines_after_split(self):
        part1 = "a" * 1999
        msg = part1 + "\n\n\nrest"
        chunks = chunk_message(msg)
        assert chunks[0] == part1
        assert chunks[1] == "rest"


def test_no_split_inside_code_block():
    """A code block that fits in one chunk should never be split."""
    code = "```python\n" + "x = 1\n" * 50 + "```"
    assert len(code) < DISCORD_MAX_LENGTH
    chunks = chunk_message(code)
    assert len(chunks) == 1
    assert chunks[0] == code


def test_code_block_at_boundary_moves_to_next_chunk():
    """If a code block would cross the boundary, start a new chunk."""
    prefix = "a" * 1950 + "\n"
    code = "```python\n" + "x = 1\n" * 10 + "```"
    content = prefix + code
    assert len(content) > DISCORD_MAX_LENGTH
    chunks = chunk_message(content)
    assert len(chunks) == 2
    assert "```python" in chunks[1]
    assert chunks[1].rstrip().endswith("```")


def test_oversized_code_block_split_with_fence():
    """A single code block > 2000 chars should be split with close/reopen fences."""
    code = "```python\n" + "x = 1\n" * 500 + "```"
    assert len(code) > DISCORD_MAX_LENGTH
    chunks = chunk_message(code)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.strip().startswith("```")
        assert chunk.strip().endswith("```")


def test_prefer_blank_line_split():
    """Should prefer splitting on blank lines over arbitrary newlines."""
    block1 = "First paragraph.\n" * 40
    block2 = "Second paragraph.\n" * 40
    block3 = "Third paragraph.\n" * 40
    content = block1 + "\n" + block2 + "\n" + block3
    chunks = chunk_message(content)
    for chunk in chunks:
        assert len(chunk) <= DISCORD_MAX_LENGTH


def test_existing_behavior_preserved():
    """Short messages should still work."""
    assert chunk_message("hello") == ["hello"]
    assert chunk_message("") == []
    assert chunk_message("a" * 2000) == ["a" * 2000]
