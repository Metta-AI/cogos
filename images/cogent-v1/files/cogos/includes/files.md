# Files API

Three capabilities for file access: `file` (single key), `dir` (prefix), `file_version` (history).

Use exact file keys, including suffixes like `.md` and `.json`. Inline prompt references should also keep the suffix: `@{cogos/docs/layout.md}`, not `@{cogos/docs/layout}`.

## dir — directory access

```python
# List files under a prefix
entries = dir.list("cogos/docs/")
for e in entries:
    print(e.key)

# Read a file
doc = dir.read("cogos/docs/layout.md")
print(doc.content)

# Write a file (creates or updates)
dir.write("workspace/notes.md", "my notes here")

# Delete a file
dir.delete("workspace/old-notes.md")
```

**Scoping:** `dir.scope(prefix="/workspace/", ops=["list", "read"])`

## file — single-file access

```python
# Read
content = file.read("/config/system.md")
print(content.content)

# Write
file.write("/config/system.md", "new config")

# Delete
file.delete("/config/system.md")

# Metadata (versions, timestamps)
meta = file.get_metadata("/config/system.md")
print(meta.versions, meta.created_at)
```

**Scoping:** `file.scope(key="/config/system.md", ops=["read"])`

## file_version — version history

```python
# List all versions of a file
versions = file_version.list("/logs/audit.md")
for v in versions:
    print(f"v{v.version}: {v.source} — {len(v.content)} chars")

# Add a new version
file_version.add("/logs/audit.md", "updated content")
```

**Scoping:** `file_version.scope(key="/logs/audit.md", ops=["add"])`

## Return types

All methods return Pydantic models:
- `FileContent` — id, key, version, content, read_only, source
- `FileWriteResult` — id, key, version, created, changed
- `FileSearchResult` — id, key
- `FileError` — error (string)

Check for errors: `if isinstance(result, FileError): print(result.error)`
