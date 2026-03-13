# Fibonacci demo app — minimal session-reentrant daemon.
#
# Send `fibonacci:poke` to advance the sequence by one step.
# The daemon keeps its state only in the resumed session transcript.

add_channel("fibonacci:poke", channel_type="named")
add_schema(
    "fibonacci-step",
    definition={
        "fields": {
            "index": "number",
            "value": "number",
            "previous": "number",
            "current": "number",
        }
    },
)
add_channel("fibonacci:steps", schema="fibonacci-step", channel_type="named")

add_process(
    "fibonacci",
    mode="daemon",
    content="@{apps/fibonacci/prompts/fibonacci.md}",
    runner="lambda",
    priority=1.0,
    capabilities=["channels", "dir"],
    handlers=["fibonacci:poke"],
    metadata={"session": {"mode": "process"}},
)
