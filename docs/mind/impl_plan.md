# Mind System Design

The mind is a CLI-only management layer that defines programs, tasks, triggers, and cron schedules. It has zero runtime responsibility. The brain handles all matching and execution.

## Data Flow

```
Channels/Cron/CLI --> events --> Brain (match triggers, run programs)
                                  ^
                                  |
                            Mind CLI (CRUD)
                            - programs
                            - tasks
                            - triggers
                            - cron
```

1. Events arrive from channels, cron, CLI, or other programs.
2. Brain matches events against triggers.
3. Matching trigger identifies a program to run.
4. Program may create/update tasks, emit events.
5. Brain records runs with resource usage.

## Data Model

### programs (replaces skills)

| Column   | Type | Notes                                       |
|----------|------|---------------------------------------------|
| id       | UUID | PK                                          |
| name     | TEXT | unique                                      |
| type     | TEXT | `python` or `prompt`                        |
| content  | TEXT | the actual code or prompt                   |
| includes | JSONB| list of memory keys for context             |
| tools    | JSONB| list of mind CLI commands program can call   |
| metadata | JSONB|                                             |

### tasks (modified from existing)

| Column         | Type  | Notes                                    |
|----------------|-------|------------------------------------------|
| id             | UUID  | PK                                       |
| name           | TEXT  |                                          |
| description    | TEXT  |                                          |
| status         | TEXT  | pending, running, failed, completed      |
| priority       | INT   |                                          |
| parent_task_id | UUID  | nullable, for sub-tasks                  |
| creator        | TEXT  | who/what created it                      |
| source_event   | TEXT  | event that spawned it                    |
| limits         | JSONB | `{tokens, attempts, time_seconds}`       |
| metadata       | JSONB |                                          |

Limits are defined on tasks. Actual usage is tracked in the brain's runs table.

### triggers (modified from existing)

| Column       | Type | Notes                     |
|--------------|------|---------------------------|
| id           | UUID | PK                        |
| program_name | TEXT | FK to programs.name       |
| event_pattern| TEXT | pattern to match events   |
| priority     | INT  |                           |
| enabled      | BOOL |                           |
| config       | JSONB| retry policy, etc.        |

No `trigger_type` column. No `cogent_id`. Event-only.

### cron

| Column          | Type | Notes                        |
|-----------------|------|------------------------------|
| id              | UUID | PK                           |
| cron_expression | TEXT |                              |
| event_pattern   | TEXT | event to emit on schedule    |
| enabled         | BOOL |                              |
| metadata        | JSONB|                              |

Cron is just an event source. It emits events that triggers match against.

## Schema Changes

No existing tables are deployed. Replace the current schema definitions wholesale:

1. **Replace `skills`** with `programs`.
2. **Replace `tasks`** with the new task model.
3. **Replace `triggers`** with event-only triggers.
4. **Add `cron`** table.

## CLI

```
mind program create <name> --type prompt --content "..." --content-file path.md --includes key1,key2 --tools "task create,task update"
mind program list
mind program show <name>
mind program update <name> [--content ...] [--content-file ...] [--includes ...] [--tools ...]
mind program delete <name>

mind task create <name> --description "..." --priority 5 --limits '{"tokens":1000,"attempts":3,"time_seconds":60}'
mind task list [--status pending] [--priority-above 3]
mind task update <id> --status running
mind task show <id>

mind trigger create --program <name> --pattern "github.pr.opened" --priority 10
mind trigger list [--program <name>]
mind trigger enable/disable <id>
mind trigger delete <id>

mind cron create --expression "0 */6 * * *" --event "schedule.review"
mind cron list
mind cron enable/disable <id>
mind cron delete <id>
```

All commands support `--json` flag for JSON output. Default is plain text.

## Implementation

```
src/mind/
    __init__.py
    cli.py          # click CLI, all commands
```

Models live in `src/brain/db/models.py`. DB access via `src/brain/db/repository.py`. The mind package is just the CLI.
