# CogTainer

The cogtainer is the cogent's persistent infrastructure layer — a PostgreSQL-backed data store with async CRUD, event-driven architecture, and AWS infrastructure management. It sits at the bottom of the stack: CogTainer (persistence/infra) -> CogOS (execution) -> CogWare (apps).

## Architecture

```
CLI Layer (cogtainer status/create/destroy/update)
    │
Repository (async CRUD over asyncpg pool)
    │
PostgreSQL (16 tables, JSONB metadata, LISTEN/NOTIFY)
```

## Module Structure

```
src/cogtainer/
├── __init__.py          # Package root
├── cli.py               # CogTainer CLI group (status/create/destroy)
├── update_cli.py        # Update subcommands (lambda/ecs/rds/stack/dashboard)
├── cdk/                 # CDK infrastructure definitions
├── db/
│   ├── __init__.py      # Public API exports
│   ├── models.py        # Pydantic models + enums
│   ├── repository.py    # Async Repository (RDS Data API)
│   ├── local_repository.py  # JSON-file local dev repository
│   └── migrations.py    # Schema apply/reset
├── docker/              # Dockerfile and Docker build context
├── lambdas/             # Lambda function handlers (event-router, executor, dispatcher, ingress)
└── tools/               # Build and deploy tooling
```

The database schema DDL lives in `src/cogos/db/schema.sql`.

## Quick Start

```python
from cogtainer.db import AwsCogtainerRepository

# Create repository (RDS Data API)
repo = AwsCogtainerRepository(cluster_arn=..., secret_arn=..., database=...)

# Or use LocalCogtainerRepository for local dev (JSON file)
from cogtainer.db.local_repository import LocalCogtainerRepository
repo = LocalCogtainerRepository()
```

## Tables

Both legacy (cogtainer-layer, from `schema.sql`) and CogOS tables (from `src/cogos/db/migrations/`) coexist in the database.

### Legacy / Cogtainer Tables (`schema.sql`)

| Table | Purpose |
|-------|---------|
| `schema_version` | Migration tracking |
| `memory` | Versioned named memory records |
| `memory_version` | Content versions per memory record |
| `programs` | Program definitions (name, memory, tools, runner) |
| `triggers` | Event pattern -> program wiring |
| `cron` | Cron schedules that emit events |
| `tools` | Tool definitions (Code Mode) |
| `tasks` | Work queue with status workflow |
| `conversations` | Multi-turn context routing |
| `runs` | Per-invocation execution summary |
| `traces` | Detailed execution audit (tool calls, memory ops) |
| `resources` | Resource pool and budget tracking |
| `resource_usage` | Per-run resource consumption |
| `events` | Append-only event log with causal chains |
| `alerts` | Algedonic emergency system |
| `budget` | Token/cost accounting by period |

### CogOS Tables (migrations)

| Table | Purpose |
|-------|---------|
| `cogos_file` | CogOS file store |
| `cogos_file_version` | File content versions |
| `cogos_capability` | Capability definitions |
| `cogos_process` | Process definitions and state |
| `cogos_process_capability` | Process-capability associations |
| `cogos_handler` | Channel subscription handlers |
| `cogos_delivery` | Per-handler message delivery tracking |
| `cogos_run` | CogOS execution runs |
| `cogos_trace` | CogOS execution traces |
| `cogos_meta` | CogOS metadata key-value store |
| `cogos_schema` | Schema definitions |
| `cogos_channel` | Communication channels |
| `cogos_channel_message` | Channel message history |
| `cogos_ingress_wake` | Ingress wake tracking |
| `cogos_discord_guild` | Discord guild metadata |
| `cogos_discord_channel` | Discord channel metadata |

## CLI

```bash
cogent <name> cogtainer status     # Infrastructure status
cogent <name> cogtainer create     # Deploy CloudFormation stack
cogent <name> cogtainer destroy    # Tear down stack
cogent <name> cogtainer update     # Update components (default: all)
```

Update subcommands: `all`, `lambda`, `discord`, `ecs`, `rds`, `stack`, `docker`
