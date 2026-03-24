# CogOS Sandbox

The sandbox is the execution environment for process code. It mediates all interaction between LLM-generated Python and the outside world through capability proxy objects.

## Execution Model

Processes interact with the system through `search(query)` and `run_code(code)`. Inside `run_code`, capability objects are pre-injected as top-level variables — the LLM writes natural Python against them. See `cogos/docs/capabilities.md` for capability scoping, delegation, and the built-in capabilities table.

## Sandbox Restrictions

The sandbox runs with a restricted set of Python builtins. The following are **blocked**:

- `import` / `__import__` — no module imports
- `open` — no filesystem access
- `exec` / `eval` — no nested code execution
- `getattr` / `hasattr` — no reflection on capability internals
- `compile` / `globals` / `locals` — no namespace introspection

Available builtins: `print`, `len`, `range`, `enumerate`, `zip`, `sorted`, `min`, `max`, `sum`, `str`, `int`, `float`, `list`, `dict`, `set`, `tuple`, `bool`, `isinstance`, `map`, `filter`, `any`, `all`, `abs`, `round`, `reversed`, `repr`, plus `json` for serialization and standard exception types.

## Protected Internals

Capability internal state (like `_scope`) is protected by a descriptor that raises `AttributeError` when accessed from sandbox code. This prevents LLM-generated code from inspecting its own permissions.
