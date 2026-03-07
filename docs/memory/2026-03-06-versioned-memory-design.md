# Versioned Memory System Design

## Problem

The current memory system has no versioning, no read-only protection, and no audit trail. Memories are overwritten in place. Polis memories loaded from disk can silently clobber manual edits. There's no way to roll back, compare versions, or protect important content from mutation.

## Goals

1. **Audit trail** — See what a memory contained at any point in time, roll back.
2. **Draft/publish workflow** — Stage new content and switch atomically via active_version pointer.
3. **A/B testing** — Multiple variants coexist, pick which is active.
4. **Protection against accidental overwrites** — Polis memories from disk don't clobber user edits; read-only flag prevents mutation.

## Data Model

### Database Schema

```sql
CREATE TABLE memory (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT UNIQUE NOT NULL,
    active_version  INT NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ DEFAULT now(),
    modified_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE memory_version (
    id          UUID DEFAULT gen_random_uuid(),
    memory_id   UUID NOT NULL REFERENCES memory(id),
    version     INT NOT NULL,
    read_only   BOOLEAN DEFAULT FALSE,
    content     TEXT DEFAULT '',
    source      TEXT DEFAULT 'cogent',
    created_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (memory_id, version)
);
```

- `memory` is the identity table. UUID primary key means names are renamable without cascading.
- `memory_version` stores one row per version. `source` is a string: `"polis"`, `"cogent"`, or `"user:<username>"`.
- `active_version` on `memory` points to which version is live.

### Pydantic Models

```python
class MemoryVersion(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    memory_id: UUID
    version: int
    read_only: bool = False
    content: str = ""
    source: str = "cogent"
    created_at: datetime | None = None

class Memory(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    active_version: int = 1
    versions: dict[int, MemoryVersion] = Field(default_factory=dict)
    created_at: datetime | None = None
    modified_at: datetime | None = None
```

### What's Removed

- `MemoryScope` enum — replaced by `source: str`
- `provenance: dict` — replaced by `source`
- `embedding: list[float]` — dropped (can add back when semantic search is wired)
- `MemoryRecord` — replaced by `Memory` + `MemoryVersion`

## Store Logic

### Upsert Flow

1. Look up `memory` by name.
2. If exists, fetch active version's `MemoryVersion`.
3. If active version is `read_only` — raise `MemoryReadOnlyError`.
4. If content unchanged — return existing (no version bump).
5. If content changed — create new version (max version + 1), update `memory.active_version`.
6. If memory doesn't exist — create `memory` row + version 1, create head pointer.

### Polis Sync Flow (mind update)

```python
for mem in load_memories_from_dir(memories_dir):
    existing = store.get_by_name(mem.name)

    if not existing:
        # New memory: create v1, read_only=True, source="polis"
        store.create(mem.name, mem.content, source="polis", read_only=True)

    elif existing.active_source.startswith("user:"):
        # User override: skip (respect customization)
        skipped += 1

    elif existing.active_content == mem.content:
        # Unchanged: no version bloat
        unchanged += 1

    else:
        # Polis content changed: new version, auto-activate
        store.new_version(mem.name, mem.content, source="polis", read_only=True)
        updated += 1
```

- `--force` flag overrides the `user:*` skip — creates new polis version and activates it.
- Warning printed: `WARNING: overriding user customization for /foo (was user:daveey v3, now polis v4)`
- Old user version preserved — user can `mind memory activate /foo 3` to switch back.

### Read-Only Enforcement

- Enforced at **store level** (not repository). Repository stays a dumb persistence layer.
- `upsert()` checks read_only on active version — raises `MemoryReadOnlyError`.
- `delete()` checks read_only — raises `MemoryReadOnlyError`.
- `activate()` and `set_readonly()` always work (management operations, not content mutations).
- `put --force` creates a new version rather than mutating the old one, so read_only on the old version doesn't block it.

### Key Resolution

`resolve_keys()` works the same as today (ancestor/child init expansion) but resolves through `memory.active_version` to get the active version's content via a join on `memory_version`.

## CLI Commands

```
mind memory list [--prefix PREFIX] [--source SOURCE] [--limit N]
    # columns: name, active_version, source, read_only, content preview

mind memory get <name> [--version N]
    # shows full content of active (or specific) version

mind memory history <name>
    # lists all versions: version, source, read_only, created_at, content preview

mind memory put <path> [--prefix PREFIX] [--source SOURCE] [--force]
    # upserts from .md files
    # --force bypasses read_only and user-source skip logic
    # only creates new version if content changed

mind memory activate <name> <version>
    # switches active_version pointer

mind memory set-ro <name> [--version N] [--off]
    # toggles read_only on active (or specific) version

mind memory rename <old-name> <new-name>
    # updates memory.name (UUID key means no cascade needed)

mind memory delete <name> [--version N] [--yes]
    # without --version: deletes entire memory + all versions
    # with --version: deletes single version (errors if it's the active one)

mind memory status
    # counts by source, read_only stats
```

## Migration

1. Create new `memory` and `memory_version` tables.
2. For each existing row in old `memory` table:
   - Create `memory` row: `id=new_uuid, name=old.name, active_version=1`
   - Create `memory_version` row: `version=1, content=old.content, source=old.scope, read_only=(scope=="polis")`
3. Drop old `memory` table.

LocalRepository JSON shape becomes:

```json
{
  "memories": {
    "<uuid>": {
      "name": "/mind/policies/tone",
      "active_version": 2,
      "versions": {
        "1": {"content": "...", "source": "polis", "read_only": true},
        "2": {"content": "...", "source": "user:daveey", "read_only": false}
      }
    }
  }
}
```

## Code Changes Required

- `brain/db/models.py` — Replace `MemoryRecord` + `MemoryScope` with `Memory` + `MemoryVersion`
- `brain/db/repository.py` — Rewrite memory methods for two-table model
- `brain/db/local_repository.py` — Update JSON structure
- `brain/db/migrations.py` — Add migration for new schema
- `memory/store.py` — Add versioning logic, read-only enforcement, `MemoryReadOnlyError`
- `memory/cli.py` — New commands: history, activate, set-ro, rename. Update existing commands.
- `memory/context_engine.py` — Resolve through active_version join
- `mind/cli.py` — Update `mind update` polis sync logic
- `mind/memory_loader.py` — Minor: drop scope/provenance, use source
