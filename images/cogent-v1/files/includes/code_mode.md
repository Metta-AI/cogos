# Code Mode

You interact with CogOS through two tools: `search` and `run_code`.

## search(query)

Discover available capabilities by keyword. Returns names, descriptions, input/output schemas, and usage instructions.

```
search("files")     # find file-related capabilities
search("email")     # find email capabilities
search("discord")   # find messaging capabilities
search("")          # list all capabilities
```

Always search before trying to use a capability you haven't used yet.

## run_code(code)

Execute Python code in a sandboxed environment. The following objects are available in scope:

### files
Read and write persistent versioned files.
```python
doc = files.read("whoami/index")       # returns {"id", "key", "content"} or None
files.write("notes/todo", "- buy milk") # creates or updates (new version)
results = files.search("notes/")        # list files by prefix
```

### procs
Inspect and list CogOS processes.
```python
all_procs = procs.list()                # [{"id", "name", "status"}, ...]
p = procs.get("scheduler")             # get a process by name
```

### events
Emit and query the append-only event log.
```python
events.emit("task:completed", {"task": "review PR"})  # emit an event
recent = events.query("email:received", limit=5)       # query by type
```

### print
Use `print()` to return output. The stdout of your code is returned as the tool result.

## Tips

- Always `print()` results you want to see — run_code returns stdout only.
- Use `search()` to discover capabilities beyond the core proxies (email, discord, secrets, scheduler, resources).
- You can run multiple statements in one `run_code` call.
- Errors return the full traceback — read it and fix your code.
