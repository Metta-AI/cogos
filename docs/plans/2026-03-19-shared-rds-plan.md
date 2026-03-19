# Shared RDS Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move from per-cogent Aurora clusters to a single shared Aurora cluster in the polis stack with per-cogent databases.

**Architecture:** Add a `DatabaseConstruct` to the polis CDK stack. Remove `DatabaseConstruct` from the cogtainer stack. All cogent services point at the shared cluster with per-cogent `DB_NAME`. Polis services look up `db_name` from the `cogent-status` DynamoDB table instead of calling `describe_stacks`.

**Tech Stack:** AWS CDK (Python), Aurora Serverless v2, RDS Data API, DynamoDB, boto3

---

### Task 1: Add DatabaseConstruct to Polis Stack

**Files:**
- Create: `src/polis/cdk/constructs/__init__.py`
- Create: `src/polis/cdk/constructs/database.py`
- Modify: `src/polis/cdk/stacks/core.py:50-498`

**Step 1: Create the polis database construct**

Create `src/polis/cdk/constructs/__init__.py` (empty file).

Create `src/polis/cdk/constructs/database.py`:

```python
"""Shared Aurora Serverless v2 database for all cogent databases."""

from __future__ import annotations

from aws_cdk import CfnOutput, RemovalPolicy
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from constructs import Construct


class SharedDatabaseConstruct(Construct):
    """Single Aurora Serverless v2 PostgreSQL cluster shared by all cogents.

    Each cogent gets its own database on this cluster. All access is via
    the RDS Data API.
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        min_acu: float = 0.5,
        max_acu: float = 16.0,
    ) -> None:
        super().__init__(scope, id)

        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)

        self.cluster = rds.DatabaseCluster(
            self,
            "Cluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_16_4,
            ),
            default_database_name="postgres",
            enable_data_api=True,
            serverless_v2_min_capacity=min_acu,
            serverless_v2_max_capacity=max_acu,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            removal_policy=RemovalPolicy.RETAIN,
            writer=rds.ClusterInstance.serverless_v2("Writer"),
        )

        self.secret = self.cluster.secret
        self.cluster_arn = self.cluster.cluster_arn

        CfnOutput(scope, "SharedDbClusterArn", value=self.cluster_arn)
        if self.secret:
            CfnOutput(scope, "SharedDbSecretArn", value=self.secret.secret_arn)
```

**Step 2: Wire the database into the polis stack**

In `src/polis/cdk/stacks/core.py`, add after the DynamoDB StatusTable section (~line 126):

```python
from polis.cdk.constructs.database import SharedDatabaseConstruct
```

Add the construct:

```python
        # --- Shared Aurora Database ---
        self.database = SharedDatabaseConstruct(self, "SharedDb")
```

Pass cluster ARN and secret ARN to the email ingest and watcher lambdas as environment variables:

```python
        # Add to email_ingest_fn environment:
        "DB_CLUSTER_ARN": self.database.cluster_arn,
        "DB_SECRET_ARN": self.database.secret.secret_arn if self.database.secret else "",
```

```python
        # Add to watcher_fn environment:
        "DB_CLUSTER_ARN": self.database.cluster_arn,
        "DB_SECRET_ARN": self.database.secret.secret_arn if self.database.secret else "",
```

Grant the email ingest lambda and watcher Data API access to the shared cluster (replace the current wildcard `rds-data` grant):

The existing watcher and email ingest already have broad RDS Data API permissions on `"*"`, so no IAM changes needed for them.

Grant the admin role access to the shared cluster secret:
Already covered by the existing `secretsmanager:GetSecretValue` on `"*"`.

**Step 3: Run CDK synth to verify**

Run: `cd /Users/daveey/code/cogents/cogents.1 && npx cdk synth cogent-polis --no-staging 2>&1 | tail -20`
Expected: Successful synthesis with new SharedDb resources in the template.

**Step 4: Commit**

```bash
git add src/polis/cdk/constructs/
git add src/polis/cdk/stacks/core.py
git commit -m "feat(polis): add shared Aurora Serverless v2 database construct"
```

---

### Task 2: Add db_name to cogent-status DynamoDB and update cogent registration

**Files:**
- Modify: `src/polis/cli.py:597-617` (cogents_create command)

**Step 1: Add db_name to the DynamoDB item written during cogent registration**

In `src/polis/cli.py`, in the `cogents_create` function, find the `table_resource.put_item(Item={...})` call and add `"db_name"` to the item:

```python
    safe_name = name.replace(".", "-")
    db_name = f"cogent_{safe_name.replace('-', '_')}"
    ...
    table_resource.put_item(
        Item={
            "cogent_name": name,
            "db_name": db_name,           # <-- NEW
            ...
        }
    )
```

**Step 2: Commit**

```bash
git add src/polis/cli.py
git commit -m "feat(polis): write db_name to cogent-status during registration"
```

---

### Task 3: Update email ingest lambda to use DynamoDB instead of describe_stacks

**Files:**
- Modify: `src/polis/io/email/handler.py:1-128`

**Step 1: Rewrite _resolve_db to use DynamoDB**

Replace the entire `_resolve_db` function and its dependencies. The new version:
- Gets `DB_CLUSTER_ARN` and `DB_SECRET_ARN` from env vars (shared cluster)
- Looks up `db_name` from `cogent-status` DynamoDB table

```python
"""Email ingest Lambda — receives parsed emails from Cloudflare Email Worker.

Deployed once in polis. Resolves the target cogent's DB from DynamoDB,
then inserts the event via RDS Data API.
"""

import base64
import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

INGEST_SECRET = os.environ.get("EMAIL_INGEST_SECRET", "")
DB_CLUSTER_ARN = os.environ.get("DB_CLUSTER_ARN", "")
DB_SECRET_ARN = os.environ.get("DB_SECRET_ARN", "")
DYNAMO_TABLE = os.environ.get("DYNAMO_TABLE", "cogent-status")

_dynamodb = None
_rds = None

# Cache: cogent_name -> db_name
_db_cache: dict[str, str] = {}


def _get_dynamodb():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb


def _get_rds():
    global _rds
    if _rds is None:
        _rds = boto3.client("rds-data")
    return _rds


def _resolve_db_name(cogent_name: str) -> str:
    """Resolve a cogent's database name from DynamoDB."""
    if cogent_name in _db_cache:
        return _db_cache[cogent_name]

    table = _get_dynamodb().Table(DYNAMO_TABLE)
    resp = table.get_item(Key={"cogent_name": cogent_name})
    item = resp.get("Item")
    if not item or "db_name" not in item:
        raise ValueError(f"Cogent {cogent_name!r} not found in {DYNAMO_TABLE} or missing db_name")

    db_name = item["db_name"]
    _db_cache[cogent_name] = db_name
    return db_name


def _insert_event(cogent_name: str, event_type: str, source: str, payload: dict) -> str:
    """Insert an event into the cogent's cogos_event table via Data API."""
    db_name = _resolve_db_name(cogent_name)
    event_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    _get_rds().execute_statement(
        resourceArn=DB_CLUSTER_ARN,
        secretArn=DB_SECRET_ARN,
        database=db_name,
        sql="""
            INSERT INTO cogos_event (id, event_type, source, payload, created_at)
            VALUES (:id::uuid, :event_type, :source, :payload::jsonb, :created_at::timestamptz)
        """,
        parameters=[
            {"name": "id", "value": {"stringValue": event_id}},
            {"name": "event_type", "value": {"stringValue": event_type}},
            {"name": "source", "value": {"stringValue": source}},
            {"name": "payload", "value": {"stringValue": json.dumps(payload)}},
            {"name": "created_at", "value": {"stringValue": now}},
        ],
    )
    return event_id


def handler(event, context):
    """Lambda handler — expects API Gateway / Function URL proxy event."""
    headers = event.get("headers", {})
    auth = headers.get("authorization", headers.get("Authorization", ""))
    token = auth.removeprefix("Bearer ").strip()

    if not INGEST_SECRET or not hmac.compare_digest(token, INGEST_SECRET):
        return {"statusCode": 401, "body": json.dumps({"detail": "Invalid ingest token"})}

    try:
        raw_body = event.get("body", "{}")
        if event.get("isBase64Encoded"):
            raw_body = base64.b64decode(raw_body).decode()
        body = json.loads(raw_body)
    except (json.JSONDecodeError, Exception) as exc:
        logger.error("Failed to parse body: %s, raw=%s", exc, event.get("body", "")[:200])
        return {"statusCode": 400, "body": json.dumps({"detail": "Invalid JSON"})}

    payload = body.get("payload", {})
    cogent_name = payload.get("cogent")
    if not cogent_name:
        return {"statusCode": 400, "body": json.dumps({"detail": "Missing cogent in payload"})}

    event_type = body.get("event_type", "email:received")
    source = body.get("source", "cloudflare-email-worker")

    try:
        event_id = _insert_event(cogent_name, event_type, source, payload)
    except Exception:
        logger.exception("Failed to insert event for cogent=%s", cogent_name)
        return {"statusCode": 500, "body": json.dumps({"detail": "Failed to insert event"})}

    logger.info(
        "Ingested email event %s cogent=%s from=%s subject=%s",
        event_id, cogent_name, payload.get("from"), payload.get("subject"),
    )
    return {"statusCode": 200, "body": json.dumps({"event_id": event_id})}
```

**Step 2: Update polis CDK stack to pass DYNAMO_TABLE env var to email ingest**

In `src/polis/cdk/stacks/core.py`, add `DYNAMO_TABLE` to the email ingest lambda environment, and grant it DynamoDB read access:

```python
        # Add to email_ingest_fn environment:
        "DYNAMO_TABLE": self.status_table.table_name,
```

```python
        # Grant DynamoDB read to email ingest
        self.status_table.grant_read_data(self.email_ingest_fn)
```

The email ingest lambda no longer needs `cloudformation:DescribeStacks` — remove that IAM statement.

**Step 3: Commit**

```bash
git add src/polis/io/email/handler.py src/polis/cdk/stacks/core.py
git commit -m "feat(polis): email ingest uses DynamoDB for cogent DB lookup"
```

---

### Task 4: Remove DatabaseConstruct from cogtainer stack

**Files:**
- Modify: `src/cogtainer/cdk/stack.py:1-455`
- Modify: `src/cogtainer/cdk/constructs/compute.py:65-78`
- Modify: `src/cogtainer/cdk/config.py:14-33`

**Step 1: Add shared DB config to CogtainerConfig**

In `src/cogtainer/cdk/config.py`, remove `db_min_acu` and `db_max_acu`, and add:

```python
    shared_db_cluster_arn: str = ""
    shared_db_secret_arn: str = ""
```

**Step 2: Remove database construct from CogtainerStack**

In `src/cogtainer/cdk/stack.py`:

1. Remove the import of `DatabaseConstruct`
2. Remove `self.database = DatabaseConstruct(self, "Database", config=config)` (line 54)
3. Derive `db_name` from cogent name:
   ```python
   safe_name = config.cogent_name.replace(".", "-")
   db_name = f"cogent_{safe_name.replace('-', '_')}"
   ```
4. Replace all references to `self.database.cluster_arn` with `config.shared_db_cluster_arn`
5. Replace all references to `self.database.secret.secret_arn` with `config.shared_db_secret_arn`
6. Replace all `"DB_NAME": "cogent"` with `"DB_NAME": db_name`
7. Remove `self.database.secret` conditional checks — the shared secret ARN comes from config
8. Remove CFN outputs for `ClusterArn` and `SecretArn` (lines 124-126)

Key replacements in `_create_discord_bridge` (lines 162-269):
- `self.database.cluster_arn` → `config.shared_db_cluster_arn`
- `self.database.secret.secret_arn if self.database.secret else ""` → `config.shared_db_secret_arn`
- `"DB_NAME": "cogent"` → `"DB_NAME": db_name`

Key replacements in `_create_dashboard` (lines 271-455):
- Same pattern for `db_env` dict (lines 330-342)

**Step 3: Update ComputeConstruct**

In `src/cogtainer/cdk/constructs/compute.py`, the constructor already takes `db_cluster_arn` and `db_secret_arn` as arguments — no structural change needed. The caller in `stack.py` will pass `config.shared_db_cluster_arn` and `config.shared_db_secret_arn` instead of `self.database.cluster_arn`.

Update line 100: `"DB_NAME": "cogent"` → pass `db_name` as a new constructor parameter.

Add `db_name: str` parameter to `ComputeConstruct.__init__` and use it:

```python
    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        config: CogtainerConfig,
        db_cluster_arn: str,
        db_secret_arn: str,
        db_name: str,
        sessions_bucket: s3.IBucket,
        event_bus_name: str,
    ) -> None:
```

Change line 100: `"DB_NAME": db_name,`

**Step 4: Run CDK synth to verify**

Run: `cd /Users/daveey/code/cogents/cogents.1 && npx cdk synth cogent-test-cogtainer --no-staging 2>&1 | tail -20`
Expected: Successful synthesis without Database construct resources.

**Step 5: Commit**

```bash
git add src/cogtainer/cdk/stack.py src/cogtainer/cdk/constructs/compute.py src/cogtainer/cdk/config.py
git commit -m "feat(cogtainer): remove per-cogent database, use shared polis cluster"
```

---

### Task 5: Update CLI to resolve DB from shared cluster

**Files:**
- Modify: `src/cogtainer/cli.py` (the `_ensure_db_env` area and `update rds` command)
- Modify: `src/cogtainer/update_cli.py`

**Step 1: Update _ensure_db_env to use shared cluster info**

Find the section in `src/cogtainer/cli.py` that reads cluster ARN and secret ARN from CloudFormation stack outputs. Replace it with:

1. Read `DB_CLUSTER_ARN` and `DB_SECRET_ARN` from polis stack outputs (or a well-known SSM parameter)
2. Set `DB_NAME` to `cogent_{safe_name}` derived from the cogent name

The exact changes depend on how `_ensure_db_env` currently resolves outputs — it reads from the per-cogent cogtainer stack. Now it should read from the polis stack for the shared cluster ARN/secret, and derive the DB name from the cogent name.

Look for any references to per-cogent `ClusterArn`/`SecretArn` stack outputs and redirect them to polis.

**Step 2: Update the `update rds` CLI command**

The `update rds` command currently runs `apply_schema()` against the per-cogent cluster. It should now:
1. Resolve the shared cluster ARN from polis
2. Set `DB_NAME` to `cogent_{safe_name}`
3. Run `apply_schema()` against the shared cluster

**Step 3: Commit**

```bash
git add src/cogtainer/cli.py src/cogtainer/update_cli.py
git commit -m "feat(cli): resolve DB from shared polis cluster"
```

---

### Task 6: Add cogent database provisioning to polis CLI

**Files:**
- Modify: `src/polis/cli.py`

**Step 1: Add database creation to cogents_create**

After writing the DynamoDB item, add a step that creates the database on the shared cluster:

```python
    # 4. Create database on shared cluster
    console.print("  Creating database on shared cluster...")
    session, _ = get_polis_session()
    cfn_client = session.client("cloudformation")
    resp = cfn_client.describe_stacks(StackName="cogent-polis")
    outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}
    cluster_arn = outputs["SharedDbClusterArn"]
    secret_arn = outputs["SharedDbSecretArn"]

    rds_client = session.client("rds-data")
    try:
        rds_client.execute_statement(
            resourceArn=cluster_arn,
            secretArn=secret_arn,
            database="postgres",
            sql=f"CREATE DATABASE {db_name}",
        )
        console.print(f"  [green]Database {db_name} created[/green]")
    except rds_client.exceptions.BadRequestException as e:
        if "already exists" in str(e):
            console.print(f"  Database {db_name} already exists")
        else:
            raise

    # 5. Apply schema to the new database
    console.print("  Applying schema...")
    os.environ["DB_RESOURCE_ARN"] = cluster_arn
    os.environ["DB_SECRET_ARN"] = secret_arn
    os.environ["DB_NAME"] = db_name
    from cogos.db.migrations import apply_schema
    apply_schema()
    console.print("  [green]Schema applied[/green]")
```

**Step 2: Commit**

```bash
git add src/polis/cli.py
git commit -m "feat(polis): create per-cogent database on shared cluster during registration"
```

---

### Task 7: Update watcher lambda to stop depending on describe_stacks for DB info

**Files:**
- Modify: `src/polis/watcher/handler.py:1-167`

**Step 1: Update watcher to include db_name in status items**

The watcher currently writes items to DynamoDB based on CloudFormation stack polling. It should also ensure `db_name` is present in each item. Since the watcher already has the cogent name, it can derive `db_name`:

In the `handler` function, when building items, ensure `db_name` is included:

```python
    safe_name = cogent_name.replace(".", "-")
    db_name = f"cogent_{safe_name.replace('-', '_')}"
```

Add this to the item dict in `resolve_runtime_status` or in the watcher handler itself before writing to DynamoDB.

Check `src/polis/runtime_status.py` to see where the item dict is built and add `db_name` there.

**Step 2: Commit**

```bash
git add src/polis/watcher/handler.py src/polis/runtime_status.py
git commit -m "feat(polis): watcher writes db_name to cogent-status table"
```

---

### Task 8: Migration script for existing cogents

**Files:**
- Create: `scripts/migrate_to_shared_rds.py`

**Step 1: Write migration script**

This script:
1. Reads all cogents from the `cogent-status` DynamoDB table
2. For each cogent, creates a database on the shared cluster
3. Runs `apply_schema()` against each new database
4. Updates the DynamoDB item with `db_name`

```python
#!/usr/bin/env python3
"""Migrate existing cogents to shared RDS cluster.

Creates fresh databases on the shared cluster and applies schema.
No data migration — cogents start clean.
"""

import os
import sys

import boto3

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def main():
    session = boto3.Session(region_name="us-east-1")

    # Get shared cluster info from polis stack
    cfn = session.client("cloudformation")
    resp = cfn.describe_stacks(StackName="cogent-polis")
    outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}
    cluster_arn = outputs["SharedDbClusterArn"]
    secret_arn = outputs["SharedDbSecretArn"]

    rds_client = session.client("rds-data")
    dynamodb = session.resource("dynamodb")
    table = dynamodb.Table("cogent-status")

    # List all cogents
    items = []
    scan_params = {}
    while True:
        resp = table.scan(**scan_params)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_params["ExclusiveStartKey"] = last_key

    for item in items:
        cogent_name = item["cogent_name"]
        safe_name = cogent_name.replace(".", "-")
        db_name = f"cogent_{safe_name.replace('-', '_')}"

        print(f"Processing {cogent_name} -> {db_name}")

        # Create database
        try:
            rds_client.execute_statement(
                resourceArn=cluster_arn,
                secretArn=secret_arn,
                database="postgres",
                sql=f"CREATE DATABASE {db_name}",
            )
            print(f"  Created database {db_name}")
        except rds_client.exceptions.BadRequestException as e:
            if "already exists" in str(e):
                print(f"  Database {db_name} already exists")
            else:
                print(f"  ERROR: {e}")
                continue

        # Apply schema
        os.environ["DB_RESOURCE_ARN"] = cluster_arn
        os.environ["DB_SECRET_ARN"] = secret_arn
        os.environ["DB_NAME"] = db_name

        try:
            from cogos.db.migrations import apply_schema
            apply_schema()
            print(f"  Schema applied to {db_name}")
        except Exception as e:
            print(f"  ERROR applying schema: {e}")
            continue

        # Update DynamoDB with db_name
        table.update_item(
            Key={"cogent_name": cogent_name},
            UpdateExpression="SET db_name = :db_name",
            ExpressionAttributeValues={":db_name": db_name},
        )
        print(f"  Updated DynamoDB with db_name={db_name}")

    print("Done!")


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add scripts/migrate_to_shared_rds.py
git commit -m "feat: add migration script for shared RDS"
```

---

### Task 9: Clean up — delete old DatabaseConstruct file

**Files:**
- Delete: `src/cogtainer/cdk/constructs/database.py`

**Step 1: Verify no remaining imports**

Run: `grep -r "from cogtainer.cdk.constructs.database" src/`
Expected: No matches (all imports were removed in Task 4).

**Step 2: Delete the file**

```bash
rm src/cogtainer/cdk/constructs/database.py
```

**Step 3: Commit**

```bash
git add -A src/cogtainer/cdk/constructs/database.py
git commit -m "chore: remove per-cogent DatabaseConstruct (replaced by shared polis DB)"
```

---

### Deployment Order

1. Deploy polis stack (Task 1) — creates shared cluster
2. Run migration script (Task 8) — creates databases, applies schemas, updates DynamoDB
3. Deploy all cogtainer stacks (Task 4) — removes per-cogent clusters, points at shared
4. Reboot cogents — verify writes go to shared cluster
5. Manually delete old Aurora clusters
