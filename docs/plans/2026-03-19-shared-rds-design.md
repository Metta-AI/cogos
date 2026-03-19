# Shared RDS Design

## Motivation

Operational simplicity. Currently each cogent gets its own Aurora Serverless v2
cluster. This means N clusters to monitor, patch, and manage. Moving to a single
shared cluster in the polis stack with per-cogent databases reduces this to one.

## Architecture

### Shared Aurora Cluster in Polis

The polis CDK stack gets a new `DatabaseConstruct` that provisions a single
Aurora Serverless v2 PostgreSQL 16.4 cluster with Data API enabled and
credentials in Secrets Manager. Sized for all cogents (higher max ACU than
today's per-cogent clusters).

Each cogent gets its own database on the shared cluster (e.g.
`cogent_alice`, `cogent_bob`). A single shared credential is used for all
cogents — IAM auth via Data API provides the access control layer.

### Per-Cogent Discovery via DynamoDB

The existing `cogent-status` DynamoDB table gets a new `db_name` attribute per
cogent, storing the database name. This is written during cogent provisioning.

Polis-side services (email ingest, watcher) that need to resolve an arbitrary
cogent name to its database do a `GetItem` on `cogent-status`. This replaces the
current `describe_stacks` call in the email ingest lambda.

The shared cluster ARN and secret ARN are environment variables on all polis
lambdas — no lookup needed for these.

### Cogtainer Stack Changes

The `DatabaseConstruct` is removed from the cogtainer CDK stack entirely. No
more per-cogent Aurora clusters.

Cogtainer lambdas and ECS tasks get their DB connection info as:
- `DB_CLUSTER_ARN` and `DB_SECRET_ARN` — sourced from polis (SSM parameters or
  CFN exports), same for all cogents
- `DB_NAME` — derived from the cogent name by convention (`cogent_{safe_name}`),
  set at deploy time. No DynamoDB lookup needed since the stack knows its own
  cogent name.

Schema migrations (`apply_schema()`) run unchanged — only connection parameters
differ.

### Polis Service Changes

- **Email ingest lambda**: replace `_resolve_db()` (`describe_stacks`) with
  DynamoDB `GetItem` for `db_name`. Cluster ARN and secret ARN from env vars.
- **Watcher lambda**: same pattern — DynamoDB lookup for `db_name`.
- **Dashboard / Discord bridge**: `DB_NAME` set per-cogent at deploy time, shared
  cluster ARN/secret from env vars.

### Cogent Provisioning Flow (New)

1. `CREATE DATABASE cogent_{safe_name}` on shared cluster via Data API
2. Run `apply_schema()` against the new database
3. Write `db_name` to `cogent-status` DynamoDB table
4. Deploy cogtainer stack (no longer creates a cluster)

## Migration Plan

Big bang — no data migration, fresh databases.

1. Deploy shared cluster in polis stack.
2. For each existing cogent:
   - `CREATE DATABASE cogent_{safe_name}` on shared cluster
   - Run `apply_schema()` to create tables
   - Write `db_name` to `cogent-status` DynamoDB
3. Update all cogtainer stacks — remove `DatabaseConstruct`, point env vars at
   shared cluster. Deploy all.
4. Reboot cogents — verify writes go to shared cluster.
5. Delete old per-cogent Aurora clusters manually (RETAIN policy).
