# Fibonacci demo app — minimal session-reentrant daemon.
#
# Send `fibonacci:poke` to advance the sequence by one step.
# The daemon keeps its state only in the resumed session transcript and
# replies in its assistant output instead of emitting channel messages.

add_channel("fibonacci:poke", channel_type="named")

add_process(
    "fibonacci",
    mode="daemon",
    content="@{apps/fibonacci/fibonacci.md}",
    runner="lambda",
    priority=1.0,
    capabilities=["dir"],
    handlers=["fibonacci:poke"],
    metadata={"session": {"resume": True, "scope": "process"}},
)
