# Agent SDK Executor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `executor: "agent_sdk"` as a new executor type that turns CogOS capabilities into native Claude Agent SDK tools, eliminating the sandbox and Bedrock converse loop for coglets that opt in.

**Architecture:** New executor path alongside existing `executor: "llm"`. Capabilities are loaded from DB bindings (same as today), converted to `@tool` functions in an in-process MCP server, and passed to the Agent SDK's `query()`. Runs on ECS via Fargate instead of Lambda. Note: scoped filesystem capabilities (`boot`, `src`, `disk`, `repo`) are stored as `ProcessCapability` DB records with scope config when spawned via `CogletRuntime` / `procs.spawn()`, so `build_process_capabilities` picks them up correctly.

**Tech Stack:** `claude-agent-sdk`, existing CogOS capability system, ECS Fargate

**Spec:** `docs/superpowers/specs/2026-03-20-agent-sdk-executor-design.md`

---

### Task 1: Add `claude-agent-sdk` dependency

**Files:**
- Modify: `pyproject.toml:15-41` (dependencies list)

- [ ] **Step 1: Add dependency**

In `pyproject.toml`, add to the `dependencies` list:

```
"claude-agent-sdk>=0.1.40",
```

- [ ] **Step 2: Install and verify**

Run: `uv sync --all-extras`
Expected: succeeds, `claude-agent-sdk` installed

- [ ] **Step 3: Verify import works**

Run: `uv run python -c "from claude_agent_sdk import tool, create_sdk_mcp_server, query, ClaudeAgentOptions; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "add claude-agent-sdk dependency"
```

---

### Task 2: Extract `build_process_capabilities` from `_setup_capability_proxies`

The existing `_setup_capability_proxies` (handler.py:1185) loads capabilities from DB, instantiates them, applies scope, wraps with tracing, and injects into a `VariableTable`. We extract the capability loading + scoping into a reusable function that both the existing and new executor paths can use.

**Files:**
- Create: `src/cogos/executor/capabilities.py`
- Create: `tests/cogos/executor/__init__.py`
- Create: `tests/cogos/executor/test_capabilities.py`
- Modify: `src/cogos/executor/handler.py:1185-1264`

- [ ] **Step 1: Write the failing test**

```python
# tests/cogos/executor/test_capabilities.py
"""Tests for build_process_capabilities — extracts capability loading from _setup_capability_proxies."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def process_id():
    return uuid4()


class TestBuildProcessCapabilities:
    def test_returns_empty_dict_when_no_bindings(self, repo, process_id):
        repo.list_process_capabilities.return_value = []
        from cogos.executor.capabilities import build_process_capabilities

        result = build_process_capabilities(process_id, repo)
        assert result == {}

    def test_loads_capability_and_applies_scope(self, repo, process_id):
        pc = MagicMock()
        pc.name = "mem"
        pc.capability = uuid4()
        pc.config = {"keys": ["test/*"]}

        cap_model = MagicMock()
        cap_model.name = "memory"
        cap_model.handler = "cogos.capabilities.secrets:SecretsCapability"
        cap_model.enabled = True

        repo.list_process_capabilities.return_value = [pc]
        repo.get_capability.return_value = cap_model

        with patch("cogos.executor.capabilities.importlib") as mock_importlib:
            mock_cls = MagicMock()
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_scoped = MagicMock()
            mock_instance.scope.return_value = mock_scoped

            mock_mod = MagicMock()
            setattr(mock_mod, "SecretsCapability", mock_cls)
            mock_importlib.import_module.return_value = mock_mod

            from cogos.executor.capabilities import build_process_capabilities

            result = build_process_capabilities(process_id, repo)

        assert "mem" in result
        mock_instance.scope.assert_called_once_with(keys=["test/*"])

    def test_skips_disabled_capabilities(self, repo, process_id):
        pc = MagicMock()
        pc.name = "mem"
        pc.capability = uuid4()
        pc.config = None

        cap_model = MagicMock()
        cap_model.enabled = False

        repo.list_process_capabilities.return_value = [pc]
        repo.get_capability.return_value = cap_model

        from cogos.executor.capabilities import build_process_capabilities

        result = build_process_capabilities(process_id, repo)
        assert result == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cogos/executor/test_capabilities.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Implement `build_process_capabilities`**

```python
# src/cogos/executor/capabilities.py
"""Capability loading for executor — builds scoped capability instances from DB bindings."""

from __future__ import annotations

import importlib
import inspect
import logging
from typing import Any
from uuid import UUID

from cogos.db.repository import Repository

logger = logging.getLogger(__name__)


def build_process_capabilities(
    process_id: UUID,
    repo: Repository,
    *,
    run_id: UUID | None = None,
    trace_id: UUID | None = None,
) -> dict[str, Any]:
    """Load capability instances bound to a process, with scope applied.

    Returns dict mapping namespace name to scoped Capability instance.
    Only capabilities explicitly bound via ProcessCapability are included.
    """
    result: dict[str, Any] = {}
    pcs = repo.list_process_capabilities(process_id)

    for pc in pcs:
        cap_model = repo.get_capability(pc.capability)
        if cap_model is None or not cap_model.enabled:
            continue

        ns = pc.name or (cap_model.name.split("/")[0] if "/" in cap_model.name else cap_model.name)
        handler_path = cap_model.handler
        if not handler_path:
            continue

        if ":" in handler_path:
            mod_path, attr_name = handler_path.rsplit(":", 1)
        elif "." in handler_path:
            mod_path, attr_name = handler_path.rsplit(".", 1)
        else:
            continue

        try:
            mod = importlib.import_module(mod_path)
            handler_cls = getattr(mod, attr_name)
            if not inspect.isclass(handler_cls):
                result[ns] = handler_cls
                continue

            init_params = inspect.signature(handler_cls.__init__).parameters
            has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in init_params.values())
            kwargs: dict[str, Any] = {}
            if "run_id" in init_params or has_var_keyword:
                kwargs["run_id"] = run_id
            if "trace_id" in init_params or has_var_keyword:
                kwargs["trace_id"] = trace_id

            instance = handler_cls(repo, process_id, **kwargs)
            if pc.config:
                instance = instance.scope(**pc.config)

            result[ns] = instance
        except (ImportError, AttributeError) as exc:
            logger.warning("Could not load capability %s (%s): %s", cap_model.name, handler_path, exc)

    return result
```

- [ ] **Step 4: Create empty `__init__.py`**

Create `tests/cogos/executor/__init__.py` (empty file).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/cogos/executor/test_capabilities.py -v`
Expected: 3 PASSED

- [ ] **Step 6: Wire into existing `_setup_capability_proxies`**

In `src/cogos/executor/handler.py`, modify `_setup_capability_proxies` to use `build_process_capabilities` internally so both paths share the same loading logic. Replace lines 1193-1238 with:

```python
from cogos.executor.capabilities import build_process_capabilities

caps = build_process_capabilities(process.id, repo, run_id=run_id, trace_id=trace_id)

vt.set("print", print)
for ns, instance in caps.items():
    instance = _wrap_capability_with_tracing(instance, ns)
    vt.set(ns, instance)
```

Keep the `__capabilities__` summary and implicit channel creation code after this.

- [ ] **Step 7: Run full test suite to verify no regression**

Run: `uv run pytest tests/ -x -q`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add src/cogos/executor/capabilities.py tests/cogos/executor/ src/cogos/executor/handler.py
git commit -m "extract build_process_capabilities from _setup_capability_proxies"
```

---

### Task 3: Capability-to-tool generation (`build_mcp_server`)

Convert a dict of scoped Capability instances into Agent SDK `@tool` functions and an in-process MCP server.

**Files:**
- Create: `src/cogos/executor/agent_sdk.py`
- Create: `tests/cogos/executor/test_agent_sdk.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/cogos/executor/test_agent_sdk.py
"""Tests for Agent SDK tool generation from CogOS capabilities."""

from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.base import Capability


class StubCapability(Capability):
    """Test capability with typed methods for tool generation."""

    def _narrow(self, existing: dict, requested: dict) -> dict:
        return {**existing, **requested}

    def _check(self, op: str, **context: object) -> None:
        allowed = self._scope.get("ops")
        if allowed is not None and op not in allowed:
            raise PermissionError(f"'{op}' not permitted")

    def get(self, key: str) -> dict:
        """Get a value by key."""
        return {"key": key, "value": "test"}

    def put(self, key: str, value: str) -> dict:
        """Store a value."""
        return {"key": key, "status": "saved"}


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def pid():
    return uuid4()


class TestGetPublicMethods:
    def test_returns_public_methods_only(self, repo, pid):
        from cogos.executor.agent_sdk import get_public_methods

        cap = StubCapability(repo, pid)
        methods = dict(get_public_methods(cap))
        assert "get" in methods
        assert "put" in methods
        assert "_check" not in methods
        assert "_narrow" not in methods
        assert "help" not in methods
        assert "scope" not in methods


class TestSchemaFromMethod:
    def test_generates_schema_from_typed_method(self, repo, pid):
        from cogos.executor.agent_sdk import schema_from_method

        cap = StubCapability(repo, pid)
        schema = schema_from_method(cap.get)
        assert schema["type"] == "object"
        assert "key" in schema["properties"]
        assert schema["properties"]["key"]["type"] == "string"


class TestBuildMcpServer:
    def test_creates_server_with_tools(self, repo, pid):
        from cogos.executor.agent_sdk import build_mcp_server

        caps = {"mem": StubCapability(repo, pid)}
        server = build_mcp_server(caps)
        assert server is not None

    def test_tool_names_follow_convention(self, repo, pid):
        from cogos.executor.agent_sdk import build_tool_functions

        caps = {"mem": StubCapability(repo, pid)}
        tools = build_tool_functions(caps)
        names = [t.__tool_name__ for t in tools]
        assert "mem_get" in names
        assert "mem_put" in names

    @pytest.mark.asyncio
    async def test_scoped_capability_blocks_disallowed_ops(self, repo, pid):
        from cogos.executor.agent_sdk import build_tool_functions

        cap = StubCapability(repo, pid).scope(ops={"get"})
        caps = {"mem": cap}
        tools = build_tool_functions(caps)
        put_tool = next(t for t in tools if t.__tool_name__ == "mem_put")

        result = await put_tool({"key": "x", "value": "y"})
        content = result["content"][0]["text"]
        assert "not permitted" in content.lower() or "error" in content.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cogos/executor/test_agent_sdk.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `agent_sdk.py`**

```python
# src/cogos/executor/agent_sdk.py
"""Agent SDK executor — converts CogOS capabilities to @tool functions."""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any, get_type_hints

from claude_agent_sdk import tool, create_sdk_mcp_server

logger = logging.getLogger(__name__)

_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def get_public_methods(cap: Any) -> list[tuple[str, Any]]:
    """Return (name, bound_method) pairs for public methods on a capability."""
    skip = {"help", "scope"}
    results = []
    for name in dir(cap):
        if name.startswith("_") or name in skip:
            continue
        attr = getattr(cap, name, None)
        if callable(attr) and not isinstance(attr, type):
            results.append((name, attr))
    return results


def schema_from_method(method: Any) -> dict:
    """Generate JSON Schema from a method's type hints."""
    try:
        hints = get_type_hints(method)
    except Exception:
        hints = {}

    sig = inspect.signature(method)
    properties: dict[str, dict] = {}
    required: list[str] = []

    for pname, param in sig.parameters.items():
        if pname == "self":
            continue
        ptype = hints.get(pname, str)
        # Unwrap Optional/Union
        origin = getattr(ptype, "__origin__", None)
        if origin is type(None):
            continue
        args = getattr(ptype, "__args__", None)
        if args and type(None) in args:
            ptype = next(a for a in args if a is not type(None))
        else:
            if param.default is inspect.Parameter.empty:
                required.append(pname)

        json_type = _TYPE_MAP.get(ptype, "string")
        properties[pname] = {"type": json_type}

    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def build_tool_functions(capabilities: dict[str, Any]) -> list[Any]:
    """Build @tool-decorated async functions from capability instances."""
    tools = []

    for cap_name, cap in capabilities.items():
        for method_name, method in get_public_methods(cap):
            tool_name = f"{cap_name}_{method_name}"
            description = (method.__doc__ or f"{cap_name}.{method_name}").strip().split("\n")[0]
            schema = schema_from_method(method)

            @tool(tool_name, description, schema)
            async def handler(args: dict[str, Any], _cap=cap, _method=method, _name=method_name) -> dict[str, Any]:
                try:
                    _cap._check(_name, **args)
                except PermissionError as e:
                    return {"content": [{"type": "text", "text": f"Error: {e}"}]}
                try:
                    result = _method(**args)
                    if hasattr(result, "model_dump"):
                        text = json.dumps(result.model_dump(), default=str)
                    elif isinstance(result, (dict, list)):
                        text = json.dumps(result, default=str)
                    else:
                        text = str(result)
                    return {"content": [{"type": "text", "text": text}]}
                except Exception as e:
                    return {"content": [{"type": "text", "text": f"Error: {e}"}]}

            handler.__tool_name__ = tool_name
            tools.append(handler)

    return tools


def build_mcp_server(capabilities: dict[str, Any]):
    """Build an in-process SDK MCP server from capability instances."""
    tools = build_tool_functions(capabilities)
    return create_sdk_mcp_server(name="cogent", version="1.0.0", tools=tools)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/cogos/executor/test_agent_sdk.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/cogos/executor/agent_sdk.py tests/cogos/executor/test_agent_sdk.py
git commit -m "capability-to-tool generation for agent sdk executor"
```

---

### Task 4: `_execute_agent_sdk_process` and executor routing

Wire the Agent SDK execution path into the existing `execute_process()` routing.

**Files:**
- Modify: `src/cogos/executor/agent_sdk.py`
- Modify: `src/cogos/executor/handler.py:599-612` (`execute_process` routing)
- Create: `tests/cogos/executor/test_agent_sdk_executor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/cogos/executor/test_agent_sdk_executor.py
"""Tests for _execute_agent_sdk_process routing and model mapping."""

from __future__ import annotations

import pytest


class TestModelMapping:
    def test_bedrock_to_sdk_model(self):
        from cogos.executor.agent_sdk import to_sdk_model

        assert to_sdk_model("us.anthropic.claude-sonnet-4-5-20250929-v1:0") == "claude-sonnet-4-5-20250929"
        assert to_sdk_model("us.anthropic.claude-haiku-4-5-20251001-v1:0") == "claude-haiku-4-5-20251001"

    def test_short_name_passthrough(self):
        from cogos.executor.agent_sdk import to_sdk_model

        assert to_sdk_model("sonnet") == "sonnet"
        assert to_sdk_model("claude-sonnet-4-5") == "claude-sonnet-4-5"


class TestExecuteProcessRouting:
    def test_agent_sdk_executor_routes_correctly(self):
        """Verify execute_process recognizes executor='agent_sdk'."""
        from cogos.executor.handler import execute_process
        import inspect

        src = inspect.getsource(execute_process)
        assert "agent_sdk" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cogos/executor/test_agent_sdk_executor.py -v`
Expected: FAIL

- [ ] **Step 3: Add `to_sdk_model` to `agent_sdk.py`**

Append to `src/cogos/executor/agent_sdk.py`:

```python
def to_sdk_model(model_id: str) -> str:
    """Convert a Bedrock model ID to an Agent SDK model name."""
    name = model_id
    for prefix in ("us.anthropic.", "anthropic."):
        if name.startswith(prefix):
            name = name[len(prefix):]
    if name.endswith(":0"):
        name = name[:-2]
    # Strip version suffix like "-v1"
    if name.endswith("-v1"):
        name = name[:-3]
    return name
```

- [ ] **Step 4: Add `_execute_agent_sdk_process` to `agent_sdk.py`**

Append to `src/cogos/executor/agent_sdk.py`:

```python
import asyncio
from decimal import Decimal
from uuid import UUID

from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ResultMessage

from cogos.db.models import Process, Run
from cogos.db.repository import Repository
from cogos.executor.capabilities import build_process_capabilities


def execute_agent_sdk_process(
    process: Process,
    event_data: dict,
    run: Run,
    config: Any,
    repo: Repository,
    *,
    trace_id: UUID | None = None,
) -> Run:
    """Execute a process via the Claude Agent SDK. Blocking wrapper around async query()."""
    return asyncio.run(_execute_agent_sdk_process(process, event_data, run, config, repo, trace_id=trace_id))


async def _execute_agent_sdk_process(
    process: Process,
    event_data: dict,
    run: Run,
    config: Any,
    repo: Repository,
    *,
    trace_id: UUID | None = None,
) -> Run:
    # 1. Build capabilities from DB bindings
    capabilities = build_process_capabilities(process.id, repo, run_id=run.id, trace_id=trace_id)

    # 2. Generate tools and MCP server from capabilities
    tools = build_tool_functions(capabilities)
    server = create_sdk_mcp_server(name="cogent", version="1.0.0", tools=tools)
    tool_names = [f"mcp__cogent__{t.__tool_name__}" for t in tools]

    # 3. Build system prompt
    from cogos.files.context_engine import ContextEngine
    from cogos.files.store import FileStore

    file_store = FileStore(repo)
    ctx = ContextEngine(file_store)
    system_prompt = ctx.generate_full_prompt(process)
    if not system_prompt:
        system_prompt = "You are a CogOS process. Follow your instructions and use capabilities to accomplish your task."

    # 4. Build user message
    user_text = _build_user_message(process, event_data, repo)

    # 5. Run the agent
    model = to_sdk_model(process.model or config.default_model)
    run.model_version = process.model or config.default_model

    options = ClaudeAgentOptions(
        mcp_servers={"cogent": server},
        allowed_tools=tool_names,
        permission_mode="bypassPermissions",
        max_turns=getattr(config, "max_turns", 20),
        system_prompt=system_prompt,
        model=model,
    )

    async for msg in query(prompt=user_text, options=options):
        if isinstance(msg, ResultMessage):
            usage = msg.usage or {}
            run.tokens_in = usage.get("input_tokens", 0)
            run.tokens_out = usage.get("output_tokens", 0)
            run.cost_usd = Decimal(str(msg.total_cost_usd or 0))
            if msg.subtype == "success":
                run.result = msg.result
            else:
                run.error = f"Agent stopped: {msg.subtype}"

    return run


def _build_user_message(process: Process, event_data: dict, repo: Repository) -> str:
    """Build the user message from the triggering event."""
    import json

    user_text = ""
    web_request = event_data.get("web_request")
    if web_request:
        user_text += f"Incoming web request:\n{json.dumps(web_request, indent=2)}\n"
    if event_data.get("payload"):
        user_text += f"Message payload: {json.dumps(event_data['payload'], indent=2)}\n"
    if not user_text.strip():
        user_text = "Execute your task."
    return user_text
```

- [ ] **Step 5: Add routing in `execute_process`**

In `src/cogos/executor/handler.py`, in the `execute_process` function (line ~609), add before the existing LLM path:

```python
if process.executor == "agent_sdk":
    from cogos.executor.agent_sdk import execute_agent_sdk_process
    return execute_agent_sdk_process(process, event_data, run, config, repo, trace_id=trace_id)
```

- [ ] **Step 6: Guard `_estimate_cost` in `handler()`**

In `src/cogos/executor/handler.py`, there are two `_estimate_cost` call sites: the success path (~line 308) and the error path (~line 371). Guard both:

```python
# Success path (~line 308):
if run.cost_usd is None or run.cost_usd == 0:
    cost = _estimate_cost(run.model_version or "", run.tokens_in, run.tokens_out)
    run.cost_usd = cost
else:
    cost = run.cost_usd

# Error path (~line 371) — same guard:
if run.cost_usd is None or run.cost_usd == 0:
    cost = _estimate_cost(run.model_version or "", run.tokens_in, run.tokens_out)
    run.cost_usd = cost
else:
    cost = run.cost_usd
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/cogos/executor/ -v`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add src/cogos/executor/agent_sdk.py src/cogos/executor/handler.py tests/cogos/executor/test_agent_sdk_executor.py
git commit -m "agent sdk execution path with routing and model mapping"
```

---

### Task 5: Dispatcher ECS branch

Add `runner == "ecs"` support to the dispatch path so processes can be launched as ECS tasks instead of Lambda invocations.

**Files:**
- Modify: `src/cogos/runtime/ingress.py:16-55`
- Create: `src/cogos/executor/ecs_entry.py`
- Create: `tests/cogos/executor/test_ecs_dispatch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/cogos/executor/test_ecs_dispatch.py
"""Tests for ECS dispatch path in ingress."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.db.models import ProcessStatus


class TestDispatchEcs:
    def test_ecs_runner_calls_run_task(self):
        from cogos.runtime.ingress import dispatch_single_process

        repo = MagicMock()
        proc = MagicMock()
        proc.id = uuid4()
        proc.runner = "ecs"
        proc.status = ProcessStatus.RUNNABLE

        dispatch_result = MagicMock()
        dispatch_result.run_id = str(uuid4())
        dispatch_result.delivery_id = None

        ecs_client = MagicMock()
        ecs_client.run_task.return_value = {"tasks": [{"taskArn": "arn:aws:ecs:us-east-1:123:task/abc"}]}

        dispatched = dispatch_single_process(
            repo=repo,
            process=proc,
            dispatch_result=dispatch_result,
            lambda_client=None,
            ecs_client=ecs_client,
            executor_function_name="test-executor",
            ecs_cluster="test-cluster",
            ecs_task_definition="test-taskdef",
        )
        assert dispatched
        ecs_client.run_task.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cogos/executor/test_ecs_dispatch.py -v`
Expected: FAIL — `dispatch_single_process` doesn't exist or doesn't accept ECS params

- [ ] **Step 3: Refactor `dispatch_ready_processes` in `ingress.py`**

Modify `src/cogos/runtime/ingress.py` to support both Lambda and ECS dispatch:

```python
"""Shared dispatch helpers for CogOS."""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from uuid import UUID

from cogos.db.models import ProcessStatus
from cogos.runtime.dispatch import build_dispatch_event

logger = logging.getLogger(__name__)


def dispatch_single_process(
    *,
    repo,
    process,
    dispatch_result,
    lambda_client: Any | None,
    ecs_client: Any | None = None,
    executor_function_name: str,
    ecs_cluster: str = "",
    ecs_task_definition: str = "",
) -> bool:
    """Dispatch a single process run via Lambda or ECS based on process.runner."""
    payload = build_dispatch_event(repo, dispatch_result)

    if process.runner == "ecs":
        if not ecs_client:
            logger.error("ECS client not provided for runner=ecs process %s", process.id)
            return False
        try:
            response = ecs_client.run_task(
                cluster=ecs_cluster,
                taskDefinition=ecs_task_definition,
                launchType="FARGATE",
                overrides={
                    "containerOverrides": [{
                        "name": "agent-executor",
                        "environment": [
                            {"name": "DISPATCH_EVENT", "value": json.dumps(payload)},
                        ],
                    }],
                },
                networkConfiguration={
                    "awsvpcConfiguration": {
                        "subnets": os.environ.get("ECS_SUBNETS", "").split(","),
                        "securityGroups": os.environ.get("ECS_SECURITY_GROUPS", "").split(","),
                        "assignPublicIp": "DISABLED",
                    }
                },
                capacityProviderStrategy=[
                    {"capacityProvider": "FARGATE_SPOT", "weight": 1},
                ],
            )
            tasks = response.get("tasks", [])
            if not tasks:
                failures = response.get("failures", [])
                raise RuntimeError(f"ECS run_task returned no tasks: {failures}")
            return True
        except Exception as exc:
            repo.rollback_dispatch(
                process.id,
                UUID(dispatch_result.run_id),
                UUID(dispatch_result.delivery_id) if dispatch_result.delivery_id else None,
                error=str(exc),
            )
            logger.exception("Failed to launch ECS task for process %s", process.id)
            return False
    else:
        try:
            response = lambda_client.invoke(
                FunctionName=executor_function_name,
                InvocationType="Event",
                Payload=json.dumps(payload),
            )
            if response.get("StatusCode") != 202:
                raise RuntimeError(f"unexpected lambda invoke status {response.get('StatusCode')}")
            return True
        except Exception as exc:
            repo.rollback_dispatch(
                process.id,
                UUID(dispatch_result.run_id),
                UUID(dispatch_result.delivery_id) if dispatch_result.delivery_id else None,
                error=str(exc),
            )
            logger.exception("Failed to invoke executor for process %s", process.id)
            return False


def dispatch_ready_processes(
    repo,
    scheduler,
    lambda_client: Any,
    executor_function_name: str,
    process_ids: set[UUID],
    *,
    ecs_client: Any | None = None,
    ecs_cluster: str = "",
    ecs_task_definition: str = "",
) -> int:
    dispatched = 0

    for process_id in sorted(process_ids, key=str):
        proc = repo.get_process(process_id)
        if proc is None or proc.status != ProcessStatus.RUNNABLE:
            continue

        dispatch_result = scheduler.dispatch_process(process_id=str(process_id))
        if hasattr(dispatch_result, "error"):
            logger.warning("Dispatch failed for %s: %s", process_id, dispatch_result.error)
            continue

        if dispatch_single_process(
            repo=repo,
            process=proc,
            dispatch_result=dispatch_result,
            lambda_client=lambda_client,
            ecs_client=ecs_client,
            executor_function_name=executor_function_name,
            ecs_cluster=ecs_cluster,
            ecs_task_definition=ecs_task_definition,
        ):
            dispatched += 1

    return dispatched
```

- [ ] **Step 4: Create ECS entrypoint**

```python
# src/cogos/executor/ecs_entry.py
"""ECS task entrypoint — parses dispatch event and calls the executor handler."""

from __future__ import annotations

import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    event_json = os.environ.get("DISPATCH_EVENT")
    if not event_json:
        logger.error("DISPATCH_EVENT not set")
        sys.exit(1)

    event = json.loads(event_json)
    logger.info("ECS executor starting: process_id=%s run_id=%s", event.get("process_id"), event.get("run_id"))

    from cogos.executor.handler import handler

    result = handler(event)
    status = result.get("statusCode", 500)
    if status != 200:
        logger.error("Executor failed: %s", result.get("error"))
        sys.exit(1)

    logger.info("Executor completed: run_id=%s", result.get("run_id"))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/cogos/executor/test_ecs_dispatch.py -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest tests/ -x -q`
Expected: all pass (existing callers of `dispatch_ready_processes` still work — new params are optional with defaults)

- [ ] **Step 7: Commit**

```bash
git add src/cogos/runtime/ingress.py src/cogos/executor/ecs_entry.py tests/cogos/executor/test_ecs_dispatch.py
git commit -m "ecs dispatch path for agent_sdk executor"
```

---

### Task 6: Document `agent_sdk` and `ecs` in CogConfig

**Files:**
- Modify: `src/cogos/cog/cog.py:43-52`

Note: `procs.py`'s `spawn()` already accepts arbitrary strings for `executor` and `runner` — no code change needed there.

- [ ] **Step 1: No test needed — this is documentation/validation**

The `executor` and `runner` fields are plain `str` with no validation. Adding `"agent_sdk"` and `"ecs"` just means using those values. Verify existing tests still pass.

- [ ] **Step 2: Update `CogConfig` docstring**

In `src/cogos/cog/cog.py`, update the `CogConfig` class to document the new values in a comment above the fields:

```python
class CogConfig(BaseModel):
    mode: str = "one_shot"
    priority: float = 0.0
    executor: str = "llm"  # "llm" | "python" | "agent_sdk"
    model: str | None = None
    runner: str = "lambda"  # "lambda" | "ecs"
    capabilities: list = Field(default_factory=list)
    handlers: list[str] = Field(default_factory=list)
    idle_timeout_ms: int | None = None
    emoji: str = ""
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/ -x -q`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add src/cogos/cog/cog.py
git commit -m "document agent_sdk executor and ecs runner in CogConfig"
```

---

### Task 7: Local validation — run a simple coglet with `executor: "agent_sdk"`

End-to-end validation that the full path works locally.

**Files:**
- No new files — uses existing local infrastructure

- [ ] **Step 1: Verify `ANTHROPIC_API_KEY` is set**

Run: `echo $ANTHROPIC_API_KEY | head -c 10`
Expected: starts with `sk-ant-` (if not, set it or verify Secrets Manager path works)

- [ ] **Step 2: Create a test script**

```python
# tests/cogos/executor/test_agent_sdk_e2e.py
"""End-to-end test: run a simple capability set through the Agent SDK executor.

Requires ANTHROPIC_API_KEY or claude-agent-sdk auth configured.
Skip with: pytest -m "not e2e"
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.base import Capability
from cogos.db.models import Run, RunStatus


class MemoryStub(Capability):
    def __init__(self, repo, process_id, **kwargs):
        super().__init__(repo, process_id, **kwargs)
        self._store: dict = {}

    def _narrow(self, existing, requested):
        return {**existing, **requested}

    def _check(self, op, **ctx):
        pass

    def get(self, key: str) -> dict:
        """Get a value from memory."""
        return {"key": key, "value": self._store.get(key, "(not found)")}

    def put(self, key: str, value: str) -> dict:
        """Store a value in memory."""
        self._store[key] = value
        return {"key": key, "status": "saved"}


@pytest.mark.e2e
def test_agent_sdk_e2e():
    from cogos.executor.agent_sdk import build_mcp_server, build_tool_functions, to_sdk_model
    from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

    repo = MagicMock()
    pid = uuid4()
    cap = MemoryStub(repo, pid)
    caps = {"memory": cap}

    server = build_mcp_server(caps)
    tools = build_tool_functions(caps)
    tool_names = [f"mcp__cogent__{t.__tool_name__}" for t in tools]

    options = ClaudeAgentOptions(
        mcp_servers={"cogent": server},
        allowed_tools=tool_names,
        permission_mode="bypassPermissions",
        max_turns=5,
        system_prompt="You have a memory tool. Store the value 'hello world' under key 'test', then read it back and confirm.",
        model="claude-sonnet-4-5",
    )

    result_msg = None

    async def run():
        nonlocal result_msg
        async for msg in query(prompt="Do your task.", options=options):
            if isinstance(msg, ResultMessage):
                result_msg = msg

    asyncio.run(run())

    assert result_msg is not None
    assert result_msg.subtype == "success"
    assert result_msg.total_cost_usd is not None
    assert cap._store.get("test") == "hello world"
```

- [ ] **Step 3: Run the e2e test**

Run: `uv run pytest tests/cogos/executor/test_agent_sdk_e2e.py -v -m e2e`
Expected: PASS — agent stores "hello world" under key "test", reads it back

- [ ] **Step 4: Review output**

Check that:
- `result_msg.total_cost_usd` is reasonable (< $0.10 for a simple task)
- `cap._store["test"]` is `"hello world"` (agent used the tools correctly)
- No unexpected tools were available (only `memory_get`, `memory_put`)

- [ ] **Step 5: Commit**

```bash
git add tests/cogos/executor/test_agent_sdk_e2e.py
git commit -m "e2e validation for agent sdk executor"
```
