"""Schema migration runner: apply schema.sql via RDS Data API, track version."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import boto3

SCHEMA_FILE = Path(__file__).parent.parent / "schema.sql"
COGOS_MIGRATIONS_DIR = Path(__file__).parent


def _get_data_client():
    """Return (rds-data client, resource_arn, secret_arn, database)."""
    client = boto3.client("rds-data", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    resource_arn = os.environ["DB_CLUSTER_ARN"]
    secret_arn = os.environ["DB_SECRET_ARN"]
    database = os.environ.get("DB_NAME", "cogent")
    return client, resource_arn, secret_arn, database


def _execute(client, resource_arn: str, secret_arn: str, database: str, sql: str) -> dict:
    """Execute a single SQL statement via Data API."""
    return client.execute_statement(
        resourceArn=resource_arn,
        secretArn=secret_arn,
        database=database,
        sql=sql,
    )


def _execute_script(client, resource_arn: str, secret_arn: str, database: str, sql: str) -> None:
    """Execute a multi-statement SQL script in a transaction.

    Uses Data API's beginTransaction/commitTransaction to ensure FK ordering
    doesn't matter (all created atomically).
    """
    tx = client.begin_transaction(
        resourceArn=resource_arn,
        secretArn=secret_arn,
        database=database,
    )
    tx_id = tx["transactionId"]
    try:
        statements = _split_sql(sql)
        for stmt in statements:
            stmt = stmt.strip()
            if not stmt:
                continue
            client.execute_statement(
                resourceArn=resource_arn,
                secretArn=secret_arn,
                database=database,
                sql=stmt,
                transactionId=tx_id,
            )
        client.commit_transaction(
            resourceArn=resource_arn,
            secretArn=secret_arn,
            transactionId=tx_id,
        )
    except Exception:
        client.rollback_transaction(
            resourceArn=resource_arn,
            secretArn=secret_arn,
            transactionId=tx_id,
        )
        raise


def _split_sql(sql: str) -> list[str]:
    """Split SQL script into individual statements, respecting $$ blocks."""
    statements = []
    current = []
    in_dollar_block = False

    for line in sql.split("\n"):
        stripped = line.strip()

        # Track $$ delimited blocks (DO $$, CREATE FUNCTION ... AS $$, etc.)
        dollar_count = stripped.count("$$")
        if dollar_count % 2 == 1:
            # Odd number of $$ toggles the block state
            in_dollar_block = not in_dollar_block
            current.append(line)
            if not in_dollar_block and stripped.endswith(";"):
                statements.append("\n".join(current))
                current = []
            continue

        if in_dollar_block:
            current.append(line)
            continue

        # Outside dollar blocks, split on semicolons
        if stripped.endswith(";") and not stripped.startswith("--"):
            current.append(line)
            statements.append("\n".join(current))
            current = []
        else:
            current.append(line)

    # Any trailing content
    remainder = "\n".join(current).strip()
    if remainder:
        statements.append(remainder)

    return statements


def _is_redundant_migration_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "already exists" in message or "duplicate" in message


def apply_cogos_sql_migrations(
    repo,
    *,
    on_error: Callable[[str, Exception], None] | None = None,
) -> int:
    """Apply raw CogOS SQL migrations using the repository's execute method.

    Returns the number of SQL statements successfully applied (not migration files).
    """
    if not COGOS_MIGRATIONS_DIR.is_dir():
        return 0

    applied = 0
    for migration in sorted(COGOS_MIGRATIONS_DIR.glob("*.sql")):
        for stmt in _split_sql(migration.read_text()):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                repo.execute(stmt)
                applied += 1
            except Exception as exc:
                if _is_redundant_migration_error(exc):
                    continue
                if on_error is not None:
                    on_error(migration.name, exc)
                    continue
                raise

    return applied


def get_current_version(client, resource_arn: str, secret_arn: str, database: str) -> int | None:
    try:
        resp = _execute(client, resource_arn, secret_arn, database,
                        "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        records = resp.get("records", [])
        if records:
            return records[0][0]["longValue"]
        return None
    except (client.exceptions.BadRequestException, client.exceptions.DatabaseErrorException) as e:
        if "does not exist" in str(e).lower() or "relation" in str(e).lower():
            return None
        raise


# Incremental migrations keyed by target version.
MIGRATIONS: dict[int, list[str]] = {
    # Each value is a list of individual statements (Data API doesn't support multi-statement).
    5: [
        # Add status column to events table for proposed/sent tracking
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('proposed', 'sent'))",
        "CREATE INDEX IF NOT EXISTS idx_events_proposed ON events (id) WHERE status = 'proposed'",
        # Trigger to auto-emit task:run event when a task is scheduled
        """CREATE OR REPLACE FUNCTION task_scheduled_trigger() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'scheduled' AND (OLD IS NULL OR OLD.status != 'scheduled') THEN
        INSERT INTO events (event_type, source, payload, status)
        VALUES (
            'task:run',
            'db-trigger',
            jsonb_build_object('task_id', NEW.id::text, 'task_name', NEW.name),
            'proposed'
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql""",
        "DROP TRIGGER IF EXISTS task_scheduled ON tasks",
        """CREATE TRIGGER task_scheduled
    AFTER INSERT OR UPDATE OF status ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION task_scheduled_trigger()""",
        "INSERT INTO schema_version (version) VALUES (5) ON CONFLICT DO NOTHING",
    ],
    7: [
        "ALTER TABLE programs ADD COLUMN IF NOT EXISTS memory_id UUID REFERENCES memory(id)",
        "ALTER TABLE programs ADD COLUMN IF NOT EXISTS memory_version INT",
        "ALTER TABLE programs DROP COLUMN IF EXISTS content",
        "ALTER TABLE programs DROP COLUMN IF EXISTS program_type",
        "ALTER TABLE programs DROP COLUMN IF EXISTS includes",
        "INSERT INTO schema_version (version) VALUES (7) ON CONFLICT DO NOTHING",
    ],
    6: [
        # --- Create versioned memory tables ---
        """CREATE TABLE IF NOT EXISTS memory (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            TEXT UNIQUE NOT NULL,
            active_version  INT NOT NULL DEFAULT 1,
            created_at      TIMESTAMPTZ DEFAULT now(),
            modified_at     TIMESTAMPTZ DEFAULT now()
        )""",
        """CREATE TABLE IF NOT EXISTS memory_version (
            id          UUID DEFAULT gen_random_uuid(),
            memory_id   UUID NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
            version     INT NOT NULL,
            read_only   BOOLEAN DEFAULT FALSE,
            content     TEXT DEFAULT '',
            source      TEXT DEFAULT 'cogent',
            created_at  TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (memory_id, version)
        )""",
        # --- Migrate data from old memory table ---
        """INSERT INTO memory (id, name, active_version, created_at, modified_at)
           SELECT id, name, 1, created_at, updated_at
           FROM memory
           WHERE name IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM memory WHERE memory.name = memory.name)""",
        """INSERT INTO memory_version (memory_id, version, read_only, content, source, created_at)
           SELECT id, 1,
                  CASE WHEN scope = 'polis' THEN TRUE ELSE FALSE END,
                  content,
                  scope,
                  created_at
           FROM memory
           WHERE name IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1 FROM memory_version
                 WHERE memory_version.memory_id = memory.id AND memory_version.version = 1
             )""",
        # --- Rename old table to preserve it ---
        "ALTER TABLE IF EXISTS memory RENAME TO memory_legacy",
        "INSERT INTO schema_version (version) VALUES (6) ON CONFLICT DO NOTHING",
    ],
    7: [
        "ALTER TABLE triggers ADD COLUMN IF NOT EXISTS throttle_timestamps JSONB NOT NULL DEFAULT '[]'",
        "ALTER TABLE triggers ADD COLUMN IF NOT EXISTS throttle_rejected INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE triggers ADD COLUMN IF NOT EXISTS throttle_active BOOLEAN NOT NULL DEFAULT false",
        "INSERT INTO schema_version (version) VALUES (7) ON CONFLICT DO NOTHING",
    ],
    8: [
        # --- Create tools table for Code Mode ---
        """CREATE TABLE IF NOT EXISTS tools (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            TEXT NOT NULL UNIQUE,
            description     TEXT NOT NULL DEFAULT '',
            instructions    TEXT NOT NULL DEFAULT '',
            input_schema    JSONB NOT NULL DEFAULT '{}',
            handler         TEXT NOT NULL DEFAULT '',
            iam_role_arn    TEXT,
            enabled         BOOLEAN NOT NULL DEFAULT true,
            metadata        JSONB NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_tools_name ON tools (name)",
        "CREATE INDEX IF NOT EXISTS idx_tools_enabled ON tools (enabled) WHERE enabled = true",
        "INSERT INTO schema_version (version) VALUES (8) ON CONFLICT DO NOTHING",
    ],
    9: [
        "ALTER TABLE memory ADD COLUMN IF NOT EXISTS includes JSONB NOT NULL DEFAULT '[]'",
        "ALTER TABLE programs DROP COLUMN IF EXISTS memory_keys",
        "INSERT INTO schema_version (version) VALUES (9) ON CONFLICT DO NOTHING",
    ],
    10: [
        # --- Consolidate memory_v2 → memory ---
        # Drop empty memory_v2 (data lives in memory table, altered in-place by migration 6)
        "DROP TABLE IF EXISTS memory_v2 CASCADE",
        "DROP TABLE IF EXISTS memory_legacy CASCADE",
        # Ensure memory table has all required columns
        "ALTER TABLE memory ADD COLUMN IF NOT EXISTS active_version INT NOT NULL DEFAULT 1",
        "ALTER TABLE memory ADD COLUMN IF NOT EXISTS modified_at TIMESTAMPTZ DEFAULT now()",
        "ALTER TABLE memory ADD COLUMN IF NOT EXISTS includes JSONB NOT NULL DEFAULT '[]'",
        # Ensure memory_version references memory(id)
        """CREATE TABLE IF NOT EXISTS memory_version (
            id          UUID DEFAULT gen_random_uuid(),
            memory_id   UUID NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
            version     INT NOT NULL,
            read_only   BOOLEAN DEFAULT FALSE,
            content     TEXT DEFAULT '',
            source      TEXT DEFAULT 'cogent',
            created_at  TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (memory_id, version)
        )""",
        # Fix programs table (duplicate key 7 bug lost memory_id/memory_version migration)
        "ALTER TABLE programs ADD COLUMN IF NOT EXISTS memory_id UUID REFERENCES memory(id)",
        "ALTER TABLE programs ADD COLUMN IF NOT EXISTS memory_version INT",
        "ALTER TABLE programs DROP COLUMN IF EXISTS content",
        "ALTER TABLE programs DROP COLUMN IF EXISTS program_type",
        "ALTER TABLE programs DROP COLUMN IF EXISTS includes",
        "ALTER TABLE programs DROP COLUMN IF EXISTS memory_keys",
        # Clean up old memory indexes/columns
        "DROP INDEX IF EXISTS idx_memory_unique_name",
        "DROP INDEX IF EXISTS idx_memory_scope",
        "ALTER TABLE memory DROP COLUMN IF EXISTS scope",
        "ALTER TABLE memory DROP COLUMN IF EXISTS content",
        "ALTER TABLE memory DROP COLUMN IF EXISTS provenance",
        "ALTER TABLE memory DROP COLUMN IF EXISTS updated_at",
        "ALTER TABLE memory DROP COLUMN IF EXISTS embedding",
        "INSERT INTO schema_version (version) VALUES (10) ON CONFLICT DO NOTHING",
    ],
}


def apply_schema(
    resource_arn: str | None = None,
    secret_arn: str | None = None,
    database: str | None = None,
) -> int:
    """Apply schema.sql if not already applied, then run incremental migrations."""
    if resource_arn and secret_arn:
        client = boto3.client("rds-data", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        database = database or "cogent"
    else:
        client, resource_arn, secret_arn, database = _get_data_client()

    current = get_current_version(client, resource_arn, secret_arn, database)
    if current is None:
        schema_sql = SCHEMA_FILE.read_text()
        _execute_script(client, resource_arn, secret_arn, database, schema_sql)
        current = get_current_version(client, resource_arn, secret_arn, database)
        return current or 0

    for version in sorted(MIGRATIONS.keys()):
        if version > current:
            for stmt in MIGRATIONS[version]:
                _execute(client, resource_arn, secret_arn, database, stmt)
            current = version

    return current


def apply_schema_with_client(
    client,
    resource_arn: str,
    secret_arn: str,
    database: str,
) -> int:
    """Apply schema using an already-configured RDS Data API client."""
    current = get_current_version(client, resource_arn, secret_arn, database)
    if current is None:
        schema_sql = SCHEMA_FILE.read_text()
        _execute_script(client, resource_arn, secret_arn, database, schema_sql)
        current = get_current_version(client, resource_arn, secret_arn, database)
        return current or 0

    for version in sorted(MIGRATIONS.keys()):
        if version > current:
            for stmt in MIGRATIONS[version]:
                _execute(client, resource_arn, secret_arn, database, stmt)
            current = version

    return current


def reset_schema(
    resource_arn: str | None = None,
    secret_arn: str | None = None,
    database: str | None = None,
) -> int:
    """Drop all tables and re-apply schema. For testing only."""
    if resource_arn and secret_arn:
        client = boto3.client("rds-data", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        database = database or "cogent"
    else:
        client, resource_arn, secret_arn, database = _get_data_client()

    drop_sql = """
        DROP TABLE IF EXISTS memory_version CASCADE;
        DROP TABLE IF EXISTS memory CASCADE;
        DROP TABLE IF EXISTS memory_legacy CASCADE;
        DROP TABLE IF EXISTS tools CASCADE;
        DROP TABLE IF EXISTS resource_usage CASCADE;
        DROP TABLE IF EXISTS resources CASCADE;
        DROP TABLE IF EXISTS traces CASCADE;
        DROP TABLE IF EXISTS runs CASCADE;
        DROP TABLE IF EXISTS conversations CASCADE;
        DROP TABLE IF EXISTS tasks CASCADE;
        DROP TABLE IF EXISTS triggers CASCADE;
        DROP TABLE IF EXISTS programs CASCADE;
        DROP TABLE IF EXISTS memory CASCADE;
        DROP TABLE IF EXISTS events CASCADE;
        DROP TABLE IF EXISTS alerts CASCADE;
        DROP TABLE IF EXISTS budget CASCADE;
        DROP TABLE IF EXISTS schema_version CASCADE;
    """
    _execute_script(client, resource_arn, secret_arn, database, drop_sql)
    schema_sql = SCHEMA_FILE.read_text()
    _execute_script(client, resource_arn, secret_arn, database, schema_sql)

    current = get_current_version(client, resource_arn, secret_arn, database)
    return current or 0
