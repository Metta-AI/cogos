"""RunCode capability — execute Python in a sandboxed namespace."""

from cogos.db.models.capability import Capability

run_code = Capability(
    name="sandbox/run_code",
    description="Execute Python code in a sandboxed namespace with proxy objects for all bound capabilities.",
    instructions=(
        "Use this to run arbitrary Python when the task requires computation, "
        "data transformation, or orchestrating multiple capability calls. "
        "The namespace is pre-populated with proxy objects for every capability "
        "bound to the calling process."
    ),
    handler="cogos.sandbox.executor.execute",
    input_schema={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python source code to execute.",
            },
        },
        "required": ["code"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "result": {},
        },
    },
)
