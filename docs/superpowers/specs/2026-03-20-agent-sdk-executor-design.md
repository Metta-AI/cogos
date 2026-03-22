# Agent SDK Executor

Add `executor: "agent_sdk"` as a new executor type alongside the existing `executor: "llm"`. CogOS capabilities become native Claude Agent SDK tools, eliminating the sandbox Lambda and Bedrock converse loop for coglets that opt in.

## Problem

The current executor has the LLM write Python code to call capabilities via proxy objects in a restricted sandbox. This works but:

- The LLM generates code to use tools rather than using native tool_use
- A separate sandbox Lambda handles code execution (cold starts, extra invocation)
- The Bedrock converse loop, token tracking, cost estimation, and Bedrock-to-Anthropic fallback are all hand-maintained
- The sandbox requires curated builtins, safe imports, dunder blocking, and scope descriptors to prevent escape

The Claude Agent SDK provides the same agentic loop that powers Claude Code, with native tool_use, automatic retries, cost tracking, and the ability to restrict an agent to only custom-defined tools.

## Design

### Executor routing

`CogConfig` already has `executor: str = "llm"` and `runner: str = "lambda"`. We add two new valid values:

- `executor: "agent_sdk"` — routes to the new Agent SDK execution path
- `runner: "ecs"` — Agent SDK spawns a subprocess, requires ECS (not Lambda)

In `execute_process()`, routing becomes:

```python
def execute_process(process, event_data, run, config, repo, ...):
    if process.executor == "python":
        return _execute_python_process(...)
    if process.executor == "agent_sdk":
        return _execute_agent_sdk_process(...)
    # existing LLM path unchanged
    ...
```

### Capability-to-tool generation

The existing executor loads capabilities via `_setup_capability_proxies()`, which reads `ProcessCapability` bindings from the DB, dynamically imports handler classes, applies scoping, and wraps with tracing proxies. For the `agent_sdk` executor, we extract this into a reusable `build_process_capabilities(process, repo, run_id, trace_id)` function that returns a `dict[str, Capability]`, then generate `@tool`-decorated functions from it via an in-process SDK MCP server (no separate subprocess — uses `create_sdk_mcp_server` which runs tools in the same process):

```python
def build_mcp_server(capabilities: dict[str, Capability]) -> SdkMcpServer:
    tools = []
    for name, cap in capabilities.items():
        for method_name, method in get_public_methods(cap):
            @tool(f"{name}_{method_name}", method.__doc__, schema_from(method))
            async def handler(args, _cap=cap, _method=method):
                _cap._check(_method.__name__, **args)
                result = _method(**args)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}
            tools.append(handler)
    return create_sdk_mcp_server(name="cogent", version="1.0.0", tools=tools)
```

Key properties:

- **Schema generation** introspects typed method signatures and Pydantic models (same information `_method_help` in `base.py` already extracts) to produce JSON Schema per tool.
- **Scope is baked in** — the capability instance in the closure is already scoped via `_narrow`. The `_check` call is defense-in-depth.
- **Sync capability methods in async wrappers** — all existing capability methods are synchronous. The `@tool` handler is `async def` but calls them synchronously. The SDK runs custom tools in its event loop; since capability methods do short DB calls (RDS Data API, HTTP-based), blocking is minimal. If this becomes an issue, wrap in `asyncio.to_thread()`.
- **Naming convention** — `files_read`, `discord_send`, `memory_get`. Flat namespace, prefixed by capability name.
- **Scoped filesystem tools** — `fs_dir` scoped variants (`boot`, `src`, `disk`, `repo`) each become their own tool set: `boot_read`, `disk_read`, `disk_write`. Same semantics as `_add_scoped_dir_and_data`, but tools instead of proxy objects.
- **`allowed_tools`** is `[f"mcp__cogent__{t.name}" for t in tools]` — the agent literally cannot call anything outside its capability set. No Bash, no Read, no Write.

### Execution function

```python
async def _execute_agent_sdk_process(process, event_data, run, config, repo, *, trace_id=None):
    # 1. Build capabilities from DB bindings (extracted from _setup_capability_proxies)
    capabilities = build_process_capabilities(process, repo, run.id, trace_id)

    # 2. Generate MCP server from capabilities
    server = build_mcp_server(capabilities)
    tool_names = [f"mcp__cogent__{t.name}" for t in server.tools]

    # 3. Build system prompt (reuse existing ContextEngine)
    file_store = FileStore(repo)
    ctx = ContextEngine(file_store)
    system_prompt = ctx.generate_full_prompt(process)

    # 4. Build user message (extract from inline code in execute_process)
    user_text = _build_user_message(event_data, repo, process)

    # 5. Run the agent
    options = ClaudeAgentOptions(
        mcp_servers={"cogent": server},
        allowed_tools=tool_names,
        permission_mode="bypassPermissions",
        max_turns=config.max_turns,
        system_prompt=system_prompt,
        model=_map_model_id(process.model or config.default_model),
    )

    async for msg in query(prompt=user_text, options=options):
        if isinstance(msg, AssistantMessage):
            _record_tool_calls(msg, repo, run, trace_id)
        if isinstance(msg, ResultMessage):
            run.tokens_in = msg.usage.get("input_tokens", 0)
            run.tokens_out = msg.usage.get("output_tokens", 0)
            run.cost_usd = Decimal(str(msg.total_cost_usd or 0))
            run.model_version = process.model or config.default_model
            if msg.subtype == "success":
                run.result = msg.result
            else:
                run.error = f"Agent stopped: {msg.subtype}"

    return run
```

Reuses from existing path: `ContextEngine.generate_full_prompt`, user message construction (extracted to `_build_user_message`), run lifecycle (`complete_run()`, status transitions, trace links).

Replaced by the SDK: Bedrock converse loop, `SandboxExecutor`/`VariableTable`, `LLMClient`, token counting, cost estimation, tool result spilling.

### Async boundary

`_execute_agent_sdk_process` is `async def`, but the existing `execute_process()` and `handler()` are synchronous Lambda handlers. For the `agent_sdk` path, `execute_process()` wraps the call in `asyncio.run()`:

```python
if process.executor == "agent_sdk":
    return asyncio.run(_execute_agent_sdk_process(...))
```

The ECS entrypoint (`ecs_entry.py`) can use `asyncio.run()` at the top level since it owns the process.

### Session/checkpoint handling

Intentionally omitted for v1. The existing `SessionStore` infrastructure (checkpoints, manifests, steps) is tightly coupled to the Bedrock converse loop's message format. The Agent SDK manages its own context window and compaction internally. For v1, each `query()` call is a fresh session. If session resumption is needed later, the SDK's `session_id` + `resume` parameter can be wired into `SessionStore`.

`run.scope_log` is not populated by the agent_sdk path. `run.snapshot` is not populated. The `handler()` caller already handles these being empty/None.

### Cost tracking

The SDK provides `total_cost_usd` directly. The `handler()` caller should skip `_estimate_cost()` when `run.cost_usd` is already set by the executor, to avoid overwriting SDK-provided cost data with inaccurate estimates.

### Model ID mapping

The existing executor uses Bedrock model IDs (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`). The Agent SDK takes short names (`claude-sonnet-4-5`). `CogConfig.model` already supports short names via the `_MODELS` dict in `cog.py`. The agent_sdk executor uses the short name directly. The existing LLM executor continues to map short names to Bedrock IDs via `_MODELS`. A `_to_sdk_model(model_id)` function strips the Bedrock prefix for cases where a full Bedrock ID is stored.

### ECS deployment

The Agent SDK spawns a Claude Code subprocess, so it requires ECS rather than Lambda.

**Invocation flow:**

```
EventBridge/Scheduler
    -> Dispatcher Lambda
        -> runner == "lambda" -> lambda.invoke(executor)     [existing]
        -> runner == "ecs"    -> ecs.run_task(agent_executor) [new]
```

**ECS task:**

- Uses the existing executor Docker image (already has all CogOS code)
- Thin entrypoint (`ecs_entry.py`) parses event payload from container overrides, calls `handler()`
- `claude-agent-sdk` added to Docker image dependencies
- Anthropic API key from Secrets Manager (`cogent/polis/anthropic`, already provisioned)
- Fargate Spot for cost efficiency (async, latency-tolerant). Spot tasks can be interrupted with 2 minutes warning; for critical processes, fall back to on-demand Fargate

**Cold start:** Fargate provisioning is 30-60 seconds. Acceptable because LLM inference itself takes 10-30+ seconds per turn, making the provisioning overhead a fraction of total run time.

**Dispatcher change:** Add a branch for `runner == "ecs"` in the dispatcher Lambda that calls `ecs.run_task()` with the event payload as container overrides, instead of `lambda.invoke()`.

### Cross-turn state

The Agent SDK's tool model is stateless per-call, but within a single `query()` session the LLM sees all previous tool results in its conversation context. The pattern `x = files.read("foo"); ... ; channels.send(x)` becomes: LLM calls `files_read(key="foo")`, result enters context, LLM reasons, then calls `discord_send()` with data extracted from the previous result.

This is how Claude Code normally works. The SDK handles automatic context compaction when the window fills up.

## File changes

### New files

| File | Purpose |
|------|---------|
| `src/cogos/executor/agent_sdk.py` | `_execute_agent_sdk_process()`, `build_mcp_server()`, capability-to-tool generation, model ID mapping |
| `src/cogos/executor/ecs_entry.py` | ECS task entrypoint — parses event from container overrides, calls `handler()` |

### Modified files

| File | Change |
|------|--------|
| `src/cogos/executor/handler.py` | Add `executor == "agent_sdk"` routing in `execute_process()`, extract `_build_user_message()`, skip `_estimate_cost()` when `run.cost_usd` already set |
| `src/cogos/cog/cog.py` | Document `"agent_sdk"` as valid executor, `"ecs"` as valid runner |
| `src/cogos/capabilities/procs.py` | Accept `executor="agent_sdk"` and `runner="ecs"` in `spawn()` |
| `pyproject.toml` | Add `claude-agent-sdk` dependency |
| Dispatcher Lambda | Add `runner == "ecs"` branch to launch ECS task |

### Untouched

- `Capability` base class, `_scope`/`_check`/`_narrow` — reused inside tool wrappers
- `CogletRuntime._build_capabilities()` — same construction, consumed differently
- `ContextEngine` / `FileStore` — system prompt generation unchanged
- Run lifecycle in `handler()` — `complete_run()`, status transitions, trace links all stay
- Entire `executor: "llm"` path — completely untouched
- `SandboxExecutor` / `VariableTable` / `llm_client.py` — still used by `executor: "llm"`, deleted when fully migrated

## Migration

Per-coglet opt-in. One-line config change, instant rollback:

```python
# Before
config = CogConfig(executor="llm", runner="lambda", capabilities=["files", "memory", "discord"])

# After
config = CogConfig(executor="agent_sdk", runner="ecs", capabilities=["files", "memory", "discord"])
```

## Validation plan

1. **Prototype:** Pick one simple coglet (memory read/write). Implement `build_mcp_server` + `_execute_agent_sdk_process`. Run locally.
2. **Baseline comparison:** Same program on both executors. Compare task completion quality, latency (end-to-end + per-turn), token usage, cost.
3. **Scoping test:** Verify a program declared with `[memory/get]` cannot access `io/discord/send` — the tool must not exist in its session.
4. **Deployment test:** Run in ECS on Fargate. Measure cold start overhead.
5. **Go/no-go:** Write-up with data.
