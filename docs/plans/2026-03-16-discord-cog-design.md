# Discord Cog Design

## Overview

Convert the Discord message handler from a static image file (`dispatch.md`) into a coglet owned by a dedicated Discord cog. The cog monitors handler performance and proposes patches to evolve the handler prompt over time. The Discord bridge (Fargate service) remains unchanged.

## Components

### 1. Discord Bridge (unchanged)

Fargate service relaying Discord gateway events to DB channels (`io:discord:dm`, `io:discord:mention`, `io:discord:message`) and polling SQS for outbound replies. No changes.

### 2. Handler Coglet

The `dispatch.md` prompt and its structural test suite, wrapped in a coglet owned by the `discord` cog.

**Storage path:**
```
cogs/discord/coglets/handler/
  main/
    main.md              -- the handler prompt (renamed from dispatch.md)
    test_main.py         -- structural validation tests
  meta.json              -- version, test_command, patches, entrypoint, mode, model
  log                    -- append-only patch history (JSONL)
```

**Created by the Discord cog** on first boot via:
```python
cog.make_coglet(
    name="handler",
    test_command="pytest test_main.py -v",
    files={
        "main.md": initial_dispatch_content,
        "test_main.py": initial_test_content,
    },
    entrypoint="main.md",
    mode="daemon",
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    capabilities=["discord", "channels", "stdlib", "procs", "file", "data:dir"],
)
```

`make_coglet` is create-or-update: on subsequent boots it updates metadata but does not overwrite evolved code in `main/`.

**Structural test suite (`test_main.py`)** validates:
- Required sections exist: `## Flow`, `## Responding`, `## Escalation`, `## Guidelines`
- References required capabilities: `discord`, `channels`, `data`, `stdlib`, `procs`, `file`
- Contains waterline dedup pattern
- Contains escalation pattern (react + `channels.send("supervisor:help", ...)`)
- Send calls include `reply_to`
- Prompt exceeds minimum length threshold

### 3. Discord Cog (new)

A daemon process that owns the handler coglet. Monitors handler performance and proposes patches to improve it.

**Capabilities:**
- `cog` scoped to `{cog_name: "discord"}` -- can only create/modify coglets under `cogs/discord/`
- `discord` -- read Discord activity, send notifications about changes
- `channels` -- read escalation history, send to ops channels
- `dir`, `file`, `stdlib` -- standard utilities

**Subscriptions:**
- `discord-cog:review` -- event-driven triggers (escalation spikes, human requests, handler errors)
- `system:tick:hour` -- periodic backstop review

**Behavior:**

On first activation (bootstrap):
1. Call `cog.make_coglet("handler", ...)` with initial `main.md` and `test_main.py`
2. Handler coglet is now registered for the coglet boot loop

On event/tick activation (review cycle):
1. Determine trigger source
2. Gather signals:
   - Recent conversation logs from `data/discord/`
   - Escalation frequency from Discord/supervisor history
   - Coglet patch log via `handler.get_log()`
3. Assess -- exit early if handler is performing well
4. If improvement needed:
   - Read current prompt via `handler.read_file("main.md")`
   - Draft improved version
   - `handler.propose_patch(diff)` -- structural tests run automatically
   - If tests pass: `handler.merge_patch(patch_id)`
   - Post summary to ops Discord channel
5. Append summary to coglet log

## Boot Sequence

Two-phase init to avoid race between cog bootstrap and coglet startup.

**Phase 1 -- Infrastructure & Cogs:**
```python
# Infrastructure
procs.spawn("scheduler", ...)

# Cogs (bootstrap their coglets)
discord_cog_prompt = file.read("cogos/cogs/discord/cog.md").content
procs.spawn("discord-cog",
    mode="daemon",
    content=discord_cog_prompt,
    priority=5.0,
    capabilities={
        "cog": {"cog_name": "discord"},
        "discord": None, "channels": None,
        "dir": None, "file": None, "stdlib": None,
    },
    subscribe=["discord-cog:review", "system:tick:hour"])

# Other processes
procs.spawn("supervisor", ...)
procs.spawn("newsfromthefront", ...)
# ...
```

**Phase 2 -- Coglet boot loop:**
```python
# Wait for cogs to bootstrap (phase boundary)
# Then start coglets
all_coglets = coglet_factory.list()
for c in all_coglets:
    tendril = coglet.scope(coglet_id=c.coglet_id)
    files = tendril.list_files()
    if "main.md" in files or "main.py" in files:
        tendril.run(procs, capability_overrides={...})
```

**First boot:** Discord cog activates, creates handler coglet, then coglet boot loop finds and runs it as a daemon subscribing to `io:discord:dm/mention/message`.

**Subsequent boots:** `make_coglet` is idempotent (metadata-only update), coglet boot loop runs the evolved handler.

## Migration

1. Remove `discord-handle-message` spawn from init.py (replaced by coglet boot)
2. Move `images/cogent-v1/cogos/io/discord/dispatch.md` content into the cog's bootstrap as `main.md`
3. Add `images/cogent-v1/cogos/cogs/discord/cog.md` -- the cog prompt
4. Add `images/cogent-v1/cogos/cogs/discord/test_main.py` -- structural test suite (bundled for initial bootstrap)
5. Update init.py to two-phase boot: cogs first, coglet loop second
6. Add phase boundary mechanism to init (cog processes need to complete bootstrap before coglet loop runs)

## Data Flow

```
Discord Gateway
    |
    v
Discord Bridge (Fargate) -- unchanged
    |
    v
DB Channels: io:discord:{dm,mention,message}
    |
    v
Handler Coglet (reads main.md from cogs/discord/coglets/handler/main/)
    |                           ^
    v                           |
SQS replies -> Bridge -> Discord    Discord Cog (proposes patches)
                                        ^
                                        |
                                    discord-cog:review + system:tick:hour
```

## Event Triggers for `discord-cog:review`

- Supervisor forwards escalation spikes
- Human explicitly requests review (message to channel)
- Handler process errors or crashes
- System hourly tick (backstop)

## Resolved Decisions

- **Phase boundary**: Cogs run immediately on spawn, so the two-phase ordering in init.py (spawn cogs first, then coglet boot loop) is sufficient. No signaling needed.
- **Test content**: `test_main.py` is stored in the image alongside the cog prompt. Tests define the handler contract and should not be weakened by the cog. The cog reads both files from the image and passes them to `make_coglet` during bootstrap.
