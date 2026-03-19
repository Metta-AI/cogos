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

class _SandboxExit(Exception):
    """Raised by exit() in sandbox code to stop execution cleanly."""
    pass


def _sandbox_exit():
    """Stop sandbox execution. Used by processes to exit early."""
    raise _SandboxExit()


def _safe_getattr(obj, name, *default):
    """getattr that blocks dunder attribute access from sandbox code."""
    if isinstance(name, str) and name.startswith("__") and name.endswith("__"):
        raise AttributeError(f"Access to '{name}' is not allowed")
    return getattr(obj, name, *default) if default else getattr(obj, name)


def _safe_dir(obj=None):
    """dir() that filters out dunder attributes for sandbox safety."""
    if obj is None:
        return []
    return [name for name in dir(obj) if not name.startswith("_")]


def _safe_help(obj=None):
    """help() that prints capability help or public methods."""
    if obj is None:
        print("Use help(object) to see available methods.")
        return
    if hasattr(obj, "help") and callable(obj.help) and not isinstance(obj, type):
        print(obj.help())
        return
    methods = _safe_dir(obj)
    type_name = type(obj).__name__
    print(f"{type_name} methods: {', '.join(methods)}")


_SAFE_BUILTINS: dict[str, Any] = {
    # Control flow
    "exit": _sandbox_exit,
    # Output
    "print": print,
    "repr": repr,
    "format": format,
    # Collections & iteration
    "len": len,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "sorted": sorted,
    "reversed": reversed,
    "map": map,
    "filter": filter,
    "iter": iter,
    "next": next,
    "min": min,
    "max": max,
    "sum": sum,
    "any": any,
    "all": all,
    "abs": abs,
    "round": round,
    # Types & constructors
    "str": str,
    "int": int,
    "float": float,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "bool": bool,
    "bytes": bytes,
    "bytearray": bytearray,
    "slice": slice,
    # Introspection
    "isinstance": isinstance,
    "issubclass": issubclass,
    "hasattr": hasattr,
    "getattr": _safe_getattr,
    "id": id,
    "callable": callable,
    "dir": _safe_dir,
    "help": _safe_help,
    # Numeric
    "chr": chr,
    "ord": ord,
    "hex": hex,
    "oct": oct,
    "bin": bin,
    "pow": pow,
    "divmod": divmod,
    # Constants
    "None": None,
    "True": True,
    "False": False,
    # Exceptions
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "AttributeError": AttributeError,
    "NameError": NameError,
    "RuntimeError": RuntimeError,
    "StopIteration": StopIteration,
    "NotImplementedError": NotImplementedError,
    "FileNotFoundError": FileNotFoundError,
    "PermissionError": PermissionError,
    "OSError": OSError,
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
    """Executes Python code in a restricted namespace with proxy objects.

    State persists between execute() calls — variables defined in one
    run_code block are available in the next.  Capability proxies and
    builtins are always re-injected so they can't be overwritten.
    """

    def __init__(self, variable_table: VariableTable) -> None:
        self.vt = variable_table
        self._scope_log: list[dict] = []
        self._user_state: dict[str, Any] = {}
        self.error: str | None = None

    @property
    def scope_log(self) -> list[dict]:
        return self._scope_log

    def execute(self, code: str) -> str:
        """Execute Python code with proxy objects injected.

        Returns stdout+stderr output, error traceback, or "(no output)" when
        the code produces no output and raises no exception.
        """
        namespace: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}
        namespace["json"] = json

        # Carry forward user-defined state from previous executions
        namespace.update(self._user_state)

        # Re-inject capability proxies (always override user state)
        # Filter out capabilities whose names collide with safe builtins
        for k, v in self.vt.as_dict().items():
            if k not in _SAFE_BUILTINS:
                namespace[k] = v

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(code, namespace)  # noqa: S102
        except _SandboxExit:
            pass  # Clean exit requested by sandbox code
        except Exception:
            error = traceback.format_exc()
            stderr_buf.write(error)
            self.error = error

        # Persist user-defined variables for the next call.
        # Exclude builtins, capability proxies, and internal keys.
        proxy_keys = set(self.vt.as_dict().keys()) | {"__builtins__", "json"}
        for key, value in namespace.items():
            if key.startswith("_") or key in proxy_keys:
                continue
            self._user_state[key] = value

        output = stdout_buf.getvalue()
        errors = stderr_buf.getvalue()
        return (output + errors).strip() if (output or errors) else "(no output)"
