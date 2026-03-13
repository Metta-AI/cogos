# File Store

CogOS uses a versioned, hierarchical key-value store for all persistent data. Files store prompts, configs, working data, logs, and documentation.

## Keys

Files are identified by string keys that look like paths:

```
whoami/index
cogos/docs/layout
cogos/lib/scheduler
```

Keys are hierarchical — you can list files by prefix (`dir.list("cogos/docs/")`).

## Versioning

Every write creates a new version. Old versions are never overwritten.

```python
files.write("config/system", "v1 content")   # version 1
files.write("config/system", "v2 content")   # version 2
files.read("config/system")                   # returns version 2
```

Use `file_version` capability to access history:

```python
versions = file_version.list("config/system")  # all versions
old = file_version.get("config/system", version=1)
```

## Three file capabilities

| Capability | Scope | Use case |
|---|---|---|
| **file** | Single key | Read/write one specific file |
| **file_version** | Single key | Access version history |
| **dir** | Prefix | Operate on a directory subtree |

`dir` is the most common — it gives full file access under a prefix. `file` and `file_version` are for fine-grained single-key grants.

## Prompt references

Files can reference other files inline with `@{file-key}`. The context engine resolves those references recursively, depth-first, and concatenates them into the prompt.

```md
# agents/my-agent
@{whoami/index.md}
@{cogos/includes/code_mode.md}
```

When this file is used as a process prompt, the referenced files are expanded directly where they appear.

## Auto-injected includes

All files under `cogos/includes/` are automatically prepended to every process's system prompt. This is how API references and instructions are distributed to all processes.

## Read-only files

Files can be marked read-only, preventing agent modification. Useful for system configuration that shouldn't be changed at runtime.

## Source tracking

Each version records its source: `"agent"`, `"human"`, or `"system"`. This lets you audit who changed what.
