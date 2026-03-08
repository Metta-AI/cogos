# Code Mode: Sandbox Execution for Tools

Builds on [tools/design.md](design.md). Replaces Bedrock toolSpec-per-tool with two meta-tools (`search_tools` + `execute_code`) and a sandbox that runs LLM-generated Python.

Inspired by [Cloudflare Code Mode](https://blog.cloudflare.com/code-mode-mcp/) — reduces token consumption from O(N tools) to O(1) while enabling multi-step tool chaining in a single turn.

## How It Works

The executor exposes exactly two tools to Bedrock (Lambda path) or via MCP (ECS path):

1. **`search_tools(query)`** — discovers available tools by keyword. Returns name, description, instructions, and input schema for matches. Scoped to the tools declared by the program/task.

2. **`execute_code(code)`** — runs LLM-generated Python in a sandbox. Declared tools are injected as callable functions organized in dot-notation namespaces mirroring the tool hierarchy.

Example LLM-generated code:

```python
msgs = channels.gmail.check(query="is:unread", max_results=5)
for m in msgs:
    mind.memory.put(key=f"latest-from-{m['from']}", value=m["subject"])
    print(f"Stored: {m['subject']}")
```

## Tool Data Model Changes

The Tool model from `design.md` gains one field:

```python
class Tool(BaseModel):
    # ... all existing fields from design.md ...
    iam_role_arn: str | None = None  # optional IAM role for scoped access
```

- Tools without `iam_role_arn` (memory, events, task management) use the sandbox's base permissions.
- Channel tools that need external credentials (Gmail, GitHub) get a dedicated IAM role.

## search_tools

The executor handles `search_tools` directly (no sandbox invocation). It queries the tools table filtered to the program/task's declared tool names, matching `query` against `name`, `description`, and `instructions` via substring search.

Returns a list:

```json
[{
    "name": "channels.gmail.check",
    "description": "Check Gmail inbox for messages",
    "instructions": "Use this tool to check for unread messages...",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Gmail search query"},
            "max_results": {"type": "integer", "default": 10}
        }
    }
}]
```

The dotted name tells the LLM exactly how to call the tool in `execute_code`.

## execute_code: Sandbox Execution

### Namespace Construction

Tool hierarchical names map to nested `SimpleNamespace` objects:

```python
# Declared tools: ["mind/task/create", "mind/memory/put", "channels/gmail/check"]
# Produces namespace:
#   mind.task.create(name="foo", program_name="bar")
#   mind.memory.put(key="k", value="v")
#   channels.gmail.check(query="is:unread")
```

Each leaf callable wraps the tool's handler. The existing handler signature from `design.md` is `(tool_name: str, tool_input: dict, config) -> str`. The wrapper translates keyword arguments:

```python
# LLM writes: channels.gmail.check(query="is:unread")
# Wrapper calls: handler("channels/gmail/check", {"query": "is:unread"}, scoped_config)
```

### IAM Role Scoping

For tools with `iam_role_arn`:

1. Sandbox calls `sts:AssumeRole` to get temporary credentials
2. Builds a scoped config with those credentials
3. Passes the scoped config to the tool handler

For tools without `iam_role_arn`, the sandbox's base config is used (has DB access and EventBridge permissions).

### Restricted Builtins

The exec namespace includes only safe builtins:

- Allowed: `print`, `len`, `range`, `enumerate`, `zip`, `sorted`, `min`, `max`, `sum`, `str`, `int`, `float`, `list`, `dict`, `set`, `tuple`, `bool`, `isinstance`, `json` (module)
- Blocked: `__import__`, `open`, `exec`, `eval`, `compile`, `globals`, `locals`, `getattr`, `setattr`, `delattr`

### Return Value

Stdout is captured via `StringIO` redirect. On success, returns all printed output as a plain string. On exception, returns the traceback. The executor passes this back to Bedrock as the tool result, giving the LLM enough context to self-correct on errors.

## Architecture: Two Execution Paths

```
Lambda executor (handler.py):
  Bedrock Converse API
  +-- search_tools: handled in-process (DB query)
  +-- execute_code: invokes sandbox Lambda (cogent-{name}-sandbox)
      +-- mind_sandbox.load_and_wrap_tools()
      +-- mind_sandbox.execute_in_sandbox()

ECS executor (ecs_entry.py):
  Claude Code CLI (Bash, Read, Write, etc.)
  +-- MCP server (stdio subprocess) exposing search_tools + execute_code
      +-- mind_sandbox.load_and_wrap_tools()  (in-process)
      +-- mind_sandbox.execute_in_sandbox()   (in-process)
```

Both paths use the same core logic in `mind_sandbox.py`. The Lambda path invokes a separate function for isolation. The ECS path runs in-process since the ECS task is already an isolated container.

## Module Layout

```
src/brain/tools/
  mind_sandbox.py      # core logic shared by both paths
  mcp_server.py        # MCP server wrapping mind_sandbox (for ECS)

src/brain/lambdas/
  sandbox/
    __init__.py
    handler.py         # Lambda handler wrapping mind_sandbox
```

### mind_sandbox.py

Core functions:

- `search_tools(query, tool_names, repo)` — filters declared tools by keyword match against name/description/instructions, returns list of dicts with name (dotted), description, instructions, input_schema.
- `load_and_wrap_tools(tool_names, base_config, repo)` — loads Tool records from DB, imports each handler via `tool.handler` dotted path, assumes IAM roles where needed, builds nested `SimpleNamespace` tree of wrapped callables.
- `execute_in_sandbox(code, namespace)` — execs code with restricted builtins and the tool namespace, captures stdout, returns output string or traceback.

### brain/lambdas/sandbox/handler.py

Thin Lambda handler:

```python
def handler(event, context):
    code = event["code"]
    tool_names = event["tool_names"]
    cogent_name = event["cogent_name"]

    config = get_config()
    repo = get_repo()

    namespace = load_and_wrap_tools(tool_names, config, repo)
    result = execute_in_sandbox(code, namespace)
    return {"result": result}
```

### brain/tools/mcp_server.py

Lightweight MCP server (stdio transport) exposing two tools. Started as a subprocess by `ecs_entry.py` before launching Claude Code CLI, connected via `--mcp-config`.

## CDK / Deployment

### New Lambda: cogent-{name}-sandbox

Same code package as executor, different handler and IAM role.

- **Handler**: `brain.lambdas.sandbox.handler.handler`
- **Timeout**: 30 seconds
- **Memory**: 256 MB

### Sandbox IAM Role

Minimal base permissions:

- `rds-data:ExecuteStatement`, `rds-data:BatchExecuteStatement` — for core tools (memory, events, tasks)
- `secretsmanager:GetSecretValue` — on `db_secret_arn` only (DB auth)
- `events:PutEvents` — for event_send
- `sts:AssumeRole` — on `arn:aws:iam::*:role/cogent-{name}-tool-*`

Does NOT have: `bedrock:*`, `s3:*`, `lambda:InvokeFunction`, broad `secretsmanager:*`.

### Tool IAM Roles

Per-channel roles created when a channel is configured for a cogent. Example:

- `cogent-alpha-tool-gmail` — `secretsmanager:GetSecretValue` on `cogent/alpha/google-admin`
- `cogent-alpha-tool-github` — `secretsmanager:GetSecretValue` on `cogent/alpha/github`

Each role trusts the sandbox Lambda role as principal (for `sts:AssumeRole`).

### Executor Changes

- New env var: `SANDBOX_FUNCTION_NAME=cogent-{name}-sandbox`
- Executor role gains: `lambda:InvokeFunction` on the sandbox function
- `LambdaConfig` gains: `sandbox_function_name: str`

### ECS Changes

- `ecs_entry.py` starts `mcp_server.py` as a subprocess before launching Claude Code
- MCP config passed via `--mcp-config` flag
- ECS task role gains: `sts:AssumeRole` on `cogent-{name}-tool-*` (same as sandbox)

## Executor Handler Changes

`_build_tool_config()` and `_execute_tool()` are replaced. The executor always sends two fixed toolSpecs to Bedrock:

```python
TOOL_SCHEMAS = {
    "search_tools": {
        "description": "Search available tools by keyword. Returns tool names, descriptions, usage instructions, and input schemas.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword (e.g. 'gmail', 'memory', 'task')"},
            },
            "required": ["query"],
        }},
    },
    "execute_code": {
        "description": "Execute Python code with access to declared tools as callable functions. Use search_tools first to discover available tools and their schemas. Tools are organized as dot-notation namespaces (e.g. mind.task.create, channels.gmail.check).",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"},
            },
            "required": ["code"],
        }},
    },
}
```

Tool dispatch in the conversation loop:

- `search_tools` — handled in-process: calls `mind_sandbox.search_tools()`
- `execute_code` — invokes sandbox Lambda via `boto3.client("lambda").invoke()`

## Implementation Scope

Extends the implementation table from `design.md`:

| # | Area | Files |
|---|------|-------|
| 1-11 | All items from design.md | (unchanged) |
| 12 | Tool model update | `src/brain/db/models.py` — add `iam_role_arn` field to `Tool` |
| 13 | Schema update | `src/brain/db/schema.sql` — add `iam_role_arn` column to `tools` table |
| 14 | Sandbox core | `src/brain/tools/mind_sandbox.py` — `search_tools()`, `load_and_wrap_tools()`, `execute_in_sandbox()` |
| 15 | Sandbox Lambda | `src/brain/lambdas/sandbox/__init__.py`, `handler.py` |
| 16 | MCP server | `src/brain/tools/mcp_server.py` — stdio MCP server for ECS path |
| 17 | Executor rewrite | `src/brain/lambdas/executor/handler.py` — replace `TOOL_SCHEMAS`/`_build_tool_config`/`_execute_tool` with two meta-tools + sandbox Lambda invocation |
| 18 | ECS entry update | `src/brain/lambdas/executor/ecs_entry.py` — start MCP server subprocess, pass via `--mcp-config` |
| 19 | CDK: sandbox Lambda | `src/brain/cdk/constructs/compute.py` — new Lambda function, IAM role, env wiring |
| 20 | CDK: tool IAM roles | Channel-level CDK or CLI tooling to create `cogent-{name}-tool-{channel}` roles |
| 21 | Config update | `src/brain/lambdas/shared/config.py` — add `sandbox_function_name` to `LambdaConfig` |
