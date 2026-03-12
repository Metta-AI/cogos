# Capabilities

Capabilities are typed Python objects that define what a process can do. All side effects go through capabilities — there is no other way to interact with the outside world from the sandbox.

## How capabilities work

1. A `Capability` record in the DB defines the name, handler class, and schemas
2. A `ProcessCapability` record binds a capability to a process with optional scoping
3. At execution time, the handler class is instantiated and injected into the sandbox as a named variable
4. The LLM writes Python that calls methods on these objects

## No ambient authority

A process only gets capabilities it's explicitly bound to. No bindings = no capabilities. This is enforced at the sandbox level — there's no way to reach a capability you weren't granted.

## Scoping

Every capability supports `.scope()` which returns a narrowed copy. Scoping is monotonic — you can only restrict, never widen.

```python
# Full dir access under /workspace/
workspace = dir.scope("/workspace/")

# Narrow to read-only
readonly = workspace.scope(ops=["list", "read"])

# Narrow further to a subdirectory
docs = readonly.scope(prefix="/workspace/docs/")

# Cannot widen — this raises ValueError
workspace.scope(prefix="/")
```

Scope dimensions vary by capability type:
- **file** — key (single file), ops
- **dir** — prefix (directory subtree), ops
- **channels** — ops (create/send/read/subscribe), name patterns (fnmatch)
- **schemas** — ops (list/get/create)
- **discord** — channels, ops
- **email** — recipient allowlist (to), ops
- **secrets** — key patterns (fnmatch)
- **procs** — ops (list/get/spawn)

## Named grants

A process can hold multiple grants of the same capability type under different names:

```
email_me       → email scoped to ["daveey@gmail.com"]
email_team     → email scoped to ["team@company.com"]
workspace      → dir scoped to "/workspace/"
audit_log      → file_version scoped to "/logs/audit", ops=["add"]
```

The process code uses the grant name: `email_me.send(...)` not `email.send(...)`.

## Delegation

When spawning a child process, capabilities are NOT inherited. Pass them explicitly:

```python
procs.spawn("worker", capabilities={
    "channels": channels,                                  # unscoped
    "workspace": dir.scope("/workspace/", ops=["read"]),   # narrowed
})
```

Rules:
- Parent must hold the capability type it's delegating
- Child scope must be equal to or narrower than parent scope
- A scoped parent cannot delegate an unscoped grant

## Discovery

```python
capabilities.list()              # names with descriptions
capabilities.search("email")     # search by keyword
discord.help()                   # full method docs
```

## Built-in capabilities

| Name | Purpose |
|---|---|
| **file** | Single-file read/write/delete |
| **file_version** | Version history for a single file |
| **dir** | Directory-prefix access (list/read/write/create/delete) |
| **channels** | Channel messaging (create/send/read/subscribe) |
| **schemas** | Schema management (list/get/create) |
| **procs** | Process management (list/get/spawn) |
| **secrets** | Secret retrieval from AWS SSM/Secrets Manager |
| **discord** | Discord messaging, reactions, threads, DMs |
| **email** | Email send/receive via SES |
| **me** | Scoped scratch/tmp/log per process and run |
| **resources** | Resource pool availability checks |
| **scheduler** | Scheduler tick operations (scheduler only) |
