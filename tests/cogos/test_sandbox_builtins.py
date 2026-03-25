"""Tests that the sandbox executor restricts dangerous builtins."""

from cogos.sandbox.executor import SandboxExecutor, VariableTable


def _run(code: str) -> str:
    vt = VariableTable()
    executor = SandboxExecutor(vt)
    return executor.execute(code)


def test_safe_builtins_blocks_import():
    result = _run("import os")
    assert "Error" in result or "error" in result.lower()


def test_safe_builtins_blocks_open():
    result = _run("open('/etc/passwd')")
    assert "Error" in result or "error" in result.lower()


def test_safe_builtins_blocks_exec():
    result = _run("exec('1+1')")
    assert "Error" in result or "error" in result.lower()


def test_safe_builtins_blocks_eval():
    result = _run("eval('1+1')")
    assert "Error" in result or "error" in result.lower()


def test_safe_builtins_allows_basic_ops():
    result = _run(
        "print(len([3,1,2]))\n"
        "print(sorted([3,1,2]))\n"
        "print(str(42))\n"
        "print(int('7'))\n"
    )
    assert "3" in result
    assert "[1, 2, 3]" in result
    assert "42" in result
    assert "7" in result


def test_safe_builtins_allows_json():
    result = _run('print(json.dumps({"a": 1}))')
    assert '"a": 1' in result or '"a":1' in result


def test_safe_builtins_blocks_dunder_import():
    result = _run("__import__('os')")
    assert "Error" in result or "error" in result.lower()


def test_safe_builtins_allows_hasattr():
    result = _run("print(hasattr([], 'append'))")
    assert "True" in result


def test_safe_builtins_allows_getattr():
    result = _run("print(getattr('hello', 'upper')())")
    assert "HELLO" in result


def test_safe_dir_filters_dunders():
    """dir() works but filters out dunder attributes."""
    result = _run("print(dir([]))")
    assert "append" in result
    assert "__" not in result


def test_state_persists_between_executions():
    """Variables defined in one run_code call are available in the next."""
    vt = VariableTable()
    executor = SandboxExecutor(vt)
    executor.execute("x = 42")
    result = executor.execute("print(x)")
    assert "42" in result


def test_state_does_not_clobber_capabilities():
    """User variables cannot overwrite capability proxies."""
    vt = VariableTable()
    vt.set("discord", "real_capability")
    executor = SandboxExecutor(vt)
    executor.execute("discord = 'fake'")
    result = executor.execute("print(discord)")
    assert "real_capability" in result


def test_safe_builtins_blocks_type():
    """type() removed to prevent class hierarchy traversal."""
    result = _run("print(type([]))")
    assert "Error" in result or "error" in result.lower()


def test_safe_builtins_blocks_vars():
    """vars() removed to prevent object introspection."""
    result = _run("print(vars({}))")
    assert "Error" in result or "error" in result.lower()


def test_safe_builtins_blocks_setattr():
    """setattr() removed to prevent object mutation."""
    result = _run("x = []; setattr(x, 'y', 1)")
    assert "Error" in result or "error" in result.lower()


def test_safe_getattr_blocks_dunder():
    """getattr blocks dunder attribute access."""
    result = _run("print(getattr([], '__class__'))")
    assert "Error" in result or "error" in result.lower()


def test_safe_getattr_allows_normal_access():
    """getattr still works for normal attributes."""
    result = _run("print(getattr('hello', 'upper')())")
    assert "HELLO" in result


def test_safe_getattr_with_default():
    """getattr with default still works."""
    result = _run("print(getattr({}, 'missing', 'fallback'))")
    assert "fallback" in result


def test_class_hierarchy_traversal_blocked():
    """Can't traverse class hierarchy to find dangerous classes."""
    result = _run("t = getattr([], '__class__')")
    assert "Error" in result or "error" in result.lower()


def test_isinstance_still_works():
    """isinstance should still work (doesn't need type())."""
    result = _run("print(isinstance(42, int))")
    assert "True" in result


def test_safe_dir_lists_public_methods():
    """dir() on a capability object lists its public methods."""
    from unittest.mock import MagicMock
    from uuid import uuid4

    from cogos.capabilities.scheduler import SchedulerCapability

    repo = MagicMock()
    cap = SchedulerCapability(repo, uuid4())

    vt = VariableTable()
    vt.set("scheduler", cap)
    executor = SandboxExecutor(vt)
    result = executor.execute("print(dir(scheduler))")
    assert "match_messages" in result
    assert "select_processes" in result
    assert "__" not in result


def test_safe_dir_on_builtin_types():
    """dir() on strings/lists shows public methods."""
    result = _run("print(dir('hello'))")
    assert "upper" in result
    assert "__" not in result


def test_safe_help_on_capability():
    """help(obj) prints the capability help text."""
    from unittest.mock import MagicMock
    from uuid import uuid4

    from cogos.capabilities.scheduler import SchedulerCapability

    repo = MagicMock()
    cap = SchedulerCapability(repo, uuid4())

    vt = VariableTable()
    vt.set("scheduler", cap)
    executor = SandboxExecutor(vt)
    result = executor.execute("help(scheduler)")
    assert "match_messages" in result
    assert "MatchResult" in result


def test_scope_not_accessible_from_sandbox():
    """Sandbox code should not be able to read _scope from capability objects."""
    from unittest.mock import MagicMock
    from uuid import uuid4

    from cogos.capabilities.files import FilesCapability

    repo = MagicMock()
    cap = FilesCapability(repo, uuid4()).scope(prefix="/secret/", ops={"read"})

    vt = VariableTable()
    vt.set("files", cap)
    executor = SandboxExecutor(vt)
    result = executor.execute("print(files._scope)")
    assert "Error" in result or "error" in result.lower()
