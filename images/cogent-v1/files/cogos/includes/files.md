# Files API

Three capabilities for file access: `file` (single key), `dir` (prefix), `file_version` (history).

## dir — directory access

```python
# List files under a prefix
entries = dir.list("cogos/docs/")
for e in entries:
    print(e.key)

# Read a file
doc = dir.read("cogos/docs/layout")
print(doc.content)

# Write a file (creates or updates)
dir.write("workspace/notes", "my notes here")

# Delete a file
dir.delete("workspace/old-notes")
```

**Scoping:** `dir.scope(prefix="/workspace/", ops=["list", "read"])`

## file — single-file access

```python
# Read
content = file.read("/config/system")
print(content.content)

# Write
file.write("/config/system", "new config")

# Delete
file.delete("/config/system")

# Metadata (versions, timestamps)
meta = file.get_metadata("/config/system")
print(meta.versions, meta.created_at)
```

**Scoping:** `file.scope(key="/config/system", ops=["read"])`

## file_version — version history

```python
# List all versions of a file
versions = file_version.list("/config/system")
for v in versions:
    print(f"v{v.version}: {v.source} — {len(v.content)} chars")

# Add a new version
file_version.add("/config/system", "updated content")
```

**Scoping:** `file_version.scope(key="/logs/audit", ops=["add"])`

## Return types

All methods return Pydantic models:
- `FileContent` — id, key, version, content, read_only, source
- `FileWriteResult` — id, key, version, created, changed
- `FileSearchResult` — id, key
- `FileError` — error (string)

Check for errors: `if isinstance(result, FileError): print(result.error)`
