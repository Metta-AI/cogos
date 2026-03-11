"""Polis naming helpers."""

from __future__ import annotations


def expected_stack_name(cogent_name: str) -> str:
    """Return the expected brain stack name for a cogent."""
    return f"cogent-{cogent_name.replace('.', '-')}-brain"
