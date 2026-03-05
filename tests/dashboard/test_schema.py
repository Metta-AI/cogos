"""Tests for the brain database schema (canonical source of truth)."""

import pathlib

SCHEMA_PATH = pathlib.Path(__file__).resolve().parents[2] / "src" / "brain" / "db" / "schema.sql"

EXPECTED_TABLES = [
    "memory",
    "programs",
    "triggers",
    "channels",
    "tasks",
    "conversations",
    "runs",
    "traces",
    "events",
    "alerts",
    "budget",
]


def test_schema_file_readable():
    """The schema SQL file should exist and contain expected CREATE TABLE statements."""
    assert SCHEMA_PATH.exists(), f"schema.sql not found at {SCHEMA_PATH}"
    content = SCHEMA_PATH.read_text()
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in content, (
            f"Missing CREATE TABLE for '{table}'"
        )
