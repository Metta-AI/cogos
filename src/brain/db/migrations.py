"""Simple migration runner: apply schema.sql via RDS Data API, track version."""

from __future__ import annotations

import os
from pathlib import Path

import boto3

SCHEMA_FILE = Path(__file__).parent / "schema.sql"


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
    """Split SQL script into individual statements, respecting DO $$ blocks."""
    statements = []
    current = []
    in_dollar_block = False

    for line in sql.split("\n"):
        stripped = line.strip()

        # Track DO $$ ... END $$; blocks
        if not in_dollar_block and ("DO $$" in stripped or "DO $$ BEGIN" in stripped):
            in_dollar_block = True
            current.append(line)
            continue

        if in_dollar_block:
            current.append(line)
            if "END $$;" in stripped:
                in_dollar_block = False
                statements.append("\n".join(current))
                current = []
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
        DROP TABLE IF EXISTS resource_usage CASCADE;
        DROP TABLE IF EXISTS resources CASCADE;
        DROP TABLE IF EXISTS traces CASCADE;
        DROP TABLE IF EXISTS runs CASCADE;
        DROP TABLE IF EXISTS conversations CASCADE;
        DROP TABLE IF EXISTS tasks CASCADE;
        DROP TABLE IF EXISTS channels CASCADE;
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
