"""Sandbox executor — variable table, scope management, and code execution.

Provides the `run_code` meta-capability: executes Python with proxy objects
pre-injected for all capabilities bound to the process.
"""

from __future__ import annotations

import io
import json
import logging
import traceback
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

_SAFE_BUILTINS: dict[str, Any] = {
    "print": print,
    "len": len,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "sorted": sorted,
    "min": min,
    "max": max,
    "sum": sum,
    "str": str,
    "int": int,
    "float": float,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "bool": bool,
    "isinstance": isinstance,
    "map": map,
    "filter": filter,
    "any": any,
    "all": all,
    "abs": abs,
    "round": round,
    "reversed": reversed,
    "repr": repr,
    "None": None,
    "True": True,
    "False": False,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "AttributeError": AttributeError,
    "RuntimeError": RuntimeError,
    "StopIteration": StopIteration,
}


@dataclass
class ScopeEntry:
    """A variable in the scope table."""
    type: str
    context: dict = field(default_factory=dict)
    methods: dict[str, Callable] = field(default_factory=dict)
    children: dict[str, "ScopeEntry"] = field(default_factory=dict)


@dataclass
class CapabilityResult:
    """Return value from a capability handler."""
    content: Any = None
    scope: dict[str, ScopeEntry] | None = None
    release: list[str] | None = None


class VariableTable:
    """Manages the scope / variable namespace for a sandbox execution."""

    def __init__(self) -> None:
        self._vars: dict[str, Any] = {}

    def set(self, name: str, value: Any) -> None:
        self._vars[name] = value

    def get(self, name: str) -> Any:
        return self._vars.get(name)

    def remove(self, name: str) -> None:
        self._vars.pop(name, None)

    def as_dict(self) -> dict[str, Any]:
        return dict(self._vars)

    def apply_result(self, result: CapabilityResult) -> None:
        """Apply scope changes from a capability result."""
        if result.scope:
            for name, entry in result.scope.items():
                self._vars[name] = entry
        if result.release:
            for name in result.release:
                self._vars.pop(name, None)


class SandboxExecutor:
    """Executes Python code in a restricted namespace with proxy objects."""

    def __init__(self, variable_table: VariableTable) -> None:
        self.vt = variable_table
        self._scope_log: list[dict] = []

    @property
    def scope_log(self) -> list[dict]:
        return self._scope_log

    def execute(self, code: str) -> str:
        """Execute Python code with proxy objects injected.

        Returns stdout+stderr output or error traceback.
        """
        namespace: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}
        namespace["json"] = json
        namespace.update(self.vt.as_dict())

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(code, namespace)  # noqa: S102
        except Exception:
            error = traceback.format_exc()
            stderr_buf.write(error)

        output = stdout_buf.getvalue()
        errors = stderr_buf.getvalue()
        return (output + errors).strip() if (output or errors) else "(no output)"
