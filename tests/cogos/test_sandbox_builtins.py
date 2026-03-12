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
