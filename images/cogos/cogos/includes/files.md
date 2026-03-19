# Files API

Three capabilities for file access: `file` (single key), `dir` (prefix/directory), `file_version` (history).

Use exact file keys, including suffixes like `.md` and `.json`.

## Finding files

```python
# Regex search across file contents
results = dir.grep("TODO", prefix="src/", limit=20, context=1)
for r in results:
    for m in r.matches:
        print(f"{r.key}:{m.line}: {m.text}")

# Match file keys by glob pattern
files = dir.glob("**/*.py")

# Compact directory tree
print(dir.tree(depth=3))

# List files by prefix
entries = dir.list("cogos/docs/")
```

## Reading files

```python
# Full read
doc = dir.get("main.py").read()
print(doc.content, doc.total_lines)

# Line-sliced read (0-indexed)
chunk = dir.get("main.py").read(offset=50, limit=20)

# First/last N lines
top = dir.get("main.py").head(n=10)
bottom = dir.get("main.py").tail(n=10)

# Check file size without loading
info = dir.get("big.py").read(limit=1)
print(info.total_lines)
```

## Editing files

```python
# Surgical replacement (fails if old not found or not unique)
dir.get("main.py").edit(old="old_name", new="new_name")

# Replace all occurrences
dir.get("main.py").edit(old="old_name", new="new_name", replace_all=True)

# Overwrite entire file
dir.get("config.md").write("new content")

# Append to file
dir.get("log.md").append("\nnew entry")
```

## Patterns

- Explore: `dir.tree()` → `dir.grep(pattern)` → `file.read(offset, limit)` → `file.edit(old, new)`
- Bulk rename: `for r in dir.grep("old"): dir.get(r.key).edit(old="old", new="new", replace_all=True)`
- Large file: `dir.get(key).read(limit=1)` to check `total_lines`, then slice

## Return types

- `FileContent` — id, key, version, content, read_only, source, total_lines
- `FileWriteResult` — id, key, version, created, changed
- `FileSearchResult` — id, key
- `GrepResult` — key, matches (list of GrepMatch)
- `GrepMatch` — line, text, before, after
- `FileError` — error (string)

Check for errors: `if isinstance(result, FileError): print(result.error)`
