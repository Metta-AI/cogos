#!/usr/bin/env python3
"""One-time migration: create per-cogent databases on the shared RDS cluster.

Reads all cogents from the cogent-status DynamoDB table, creates a database
for each on the shared Aurora cluster, applies the schema, and updates the
DynamoDB item with the db_name.
"""

from __future__ import annotations

import os
import sys

# Allow imports from src/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def main() -> None:
    import boto3

    session = boto3.Session(region_name="us-east-1")

    # 1. Read all cogents from DynamoDB
    ddb = session.resource("dynamodb")
    table = ddb.Table("cogent-status")

    items: list[dict] = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))

    print(f"Found {len(items)} cogent(s) in cogent-status table")

    # 2. Get shared cluster ARNs from CloudFormation
    cfn = session.client("cloudformation")
    stack_resp = cfn.describe_stacks(StackName="cogent-polis")
    outputs = {
        o["OutputKey"]: o["OutputValue"]
        for o in stack_resp["Stacks"][0].get("Outputs", [])
    }
    cluster_arn = outputs["SharedDbClusterArn"]
    secret_arn = outputs["SharedDbSecretArn"]
    print(f"Shared cluster: {cluster_arn}")

    rds = session.client("rds-data")

    # 3. Migrate each cogent
    for item in items:
        name = item.get("cogent_name", "<unknown>")
        print(f"\n--- {name} ---")
        try:
            safe_name = name.replace(".", "-")
            db_name = f"cogent_{safe_name.replace('-', '_')}"

            # Create database on shared cluster
            try:
                rds.execute_statement(
                    resourceArn=cluster_arn,
                    secretArn=secret_arn,
                    database="postgres",
                    sql=f"CREATE DATABASE {db_name}",
                )
                print(f"  Created database {db_name}")
            except rds.exceptions.BadRequestException as e:
                if "already exists" in str(e):
                    print(f"  Database {db_name} already exists")
                else:
                    raise

            # Apply schema via env vars (matches how apply_schema reads config)
            os.environ["DB_CLUSTER_ARN"] = cluster_arn
            os.environ["DB_RESOURCE_ARN"] = cluster_arn
            os.environ["DB_SECRET_ARN"] = secret_arn
            os.environ["DB_NAME"] = db_name

            from cogos.db.migrations import apply_schema

            version = apply_schema()
            print(f"  Schema applied (version {version})")

            # Update DynamoDB with db_name
            table.update_item(
                Key={"cogent_name": name},
                UpdateExpression="SET db_name = :db",
                ExpressionAttributeValues={":db": db_name},
            )
            print(f"  Updated DynamoDB with db_name={db_name}")

        except Exception as e:
            print(f"  ERROR: {e}")
            continue

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
