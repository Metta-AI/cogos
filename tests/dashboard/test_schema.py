"""Tests for the dashboard database schema."""

import os
import pathlib

import pytest

SCHEMA_PATH = pathlib.Path(__file__).resolve().parents[2] / "src" / "dashboard" / "schema.sql"

EXPECTED_TABLES = [
    "conversations",
    "events",
    "executions",
    "triggers",
    "memory",
    "tasks",
    "alerts",
    "channels",
    "skills",
    "traces",
]

# Skip the entire module if no database URL is set or psycopg is unavailable.
try:
    import psycopg  # noqa: F401

    _HAS_PSYCOPG = True
except ImportError:
    _HAS_PSYCOPG = False

_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")

skip_no_db = pytest.mark.skipif(
    not _HAS_PSYCOPG or not _DATABASE_URL,
    reason="TEST_DATABASE_URL not set or psycopg not installed",
)


def _connect():
    """Return a psycopg connection to the test database."""
    return psycopg.connect(_DATABASE_URL, autocommit=True)


def _drop_tables(conn):
    """Drop all schema tables (reverse dependency order) so tests are idempotent."""
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS traces CASCADE")
        cur.execute("DROP TABLE IF EXISTS executions CASCADE")
        cur.execute("DROP TABLE IF EXISTS memory CASCADE")
        cur.execute("DROP TABLE IF EXISTS tasks CASCADE")
        cur.execute("DROP TABLE IF EXISTS alerts CASCADE")
        cur.execute("DROP TABLE IF EXISTS channels CASCADE")
        cur.execute("DROP TABLE IF EXISTS skills CASCADE")
        cur.execute("DROP TABLE IF EXISTS triggers CASCADE")
        cur.execute("DROP TABLE IF EXISTS events CASCADE")
        cur.execute("DROP TABLE IF EXISTS conversations CASCADE")


@skip_no_db
class TestSchema:
    """Verify that schema.sql creates all expected tables and indexes."""

    @pytest.fixture(autouse=True)
    def _setup_and_teardown(self):
        """Apply schema before tests, drop tables after."""
        conn = _connect()
        # Clean slate
        _drop_tables(conn)
        # Apply schema
        schema_sql = SCHEMA_PATH.read_text()
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        self.conn = conn
        yield
        _drop_tables(conn)
        conn.close()

    def test_all_tables_exist(self):
        """Every expected table should be present in the public schema."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
            existing = {row[0] for row in cur.fetchall()}
        for table in EXPECTED_TABLES:
            assert table in existing, f"Table '{table}' was not created by schema.sql"

    def test_conversations_columns(self):
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'conversations'"
            )
            cols = {row[0] for row in cur.fetchall()}
        for col in ("id", "cogent_id", "status", "metadata", "created_at"):
            assert col in cols

    def test_events_columns(self):
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'events'"
            )
            cols = {row[0] for row in cur.fetchall()}
        for col in ("id", "cogent_id", "event_type", "payload", "parent_event_id"):
            assert col in cols

    def test_executions_columns(self):
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'executions'"
            )
            cols = {row[0] for row in cur.fetchall()}
        for col in ("id", "cogent_id", "skill_name", "cost_usd", "tokens_input"):
            assert col in cols

    def test_schema_is_idempotent(self):
        """Applying the schema twice should not raise errors."""
        schema_sql = SCHEMA_PATH.read_text()
        with self.conn.cursor() as cur:
            cur.execute(schema_sql)  # second apply
        # If we get here without error, the test passes.

    def test_schema_file_exists(self):
        """Sanity check that the schema file is where we expect it."""
        assert SCHEMA_PATH.exists()


# This test does NOT require a database connection.
def test_schema_file_readable():
    """The schema SQL file should exist and contain expected CREATE TABLE statements."""
    assert SCHEMA_PATH.exists(), f"schema.sql not found at {SCHEMA_PATH}"
    content = SCHEMA_PATH.read_text()
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in content, (
            f"Missing CREATE TABLE for '{table}'"
        )
