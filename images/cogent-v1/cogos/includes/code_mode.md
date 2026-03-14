# Code Mode

You interact with CogOS through two tools: `search` and `run_code`.

## search(query)

Discover available capabilities by keyword. Returns names, descriptions, schemas, and usage instructions.

```
search("files")     # find file-related capabilities
search("email")     # find email capabilities
search("")          # list all capabilities
```

Always search before using a capability you haven't used yet.

## run_code(code)

Execute Python in the sandbox. Capability objects are pre-injected as top-level variables. `json` is also pre-loaded. Use `print()` to see results — stdout is returned as the tool result. Do NOT use `import` — it is not available.

## Tips

- Always `print()` results — run_code returns stdout only.
- Use `search()` to discover capabilities beyond what's in scope.
- You can run multiple statements in one `run_code` call.
- Errors return the full traceback — read it and fix your code.
- Read `cogos/docs/layout.md` for file organization.
- Use `dir.list("cogos/docs/")` to discover other docs, and read them by full key including the `.md` suffix.
