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
