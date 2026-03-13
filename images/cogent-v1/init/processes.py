add_process(
    "scheduler",
    mode="daemon",
    content="@{cogos/lib/scheduler.md}",
    runner="lambda",
    priority=100.0,
    capabilities=[
        "scheduler/match_channel_messages",
        "scheduler/select_processes",
        "scheduler/dispatch_process",
        "scheduler/unblock_processes",
        "scheduler/kill_process",
        "channels",
    ],
    handlers=[],
)

add_process(
    "discord-handle-message",
    mode="daemon",
    content="@{cogos/io/discord/dispatch.md}",
    runner="lambda",
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    priority=10.0,
    capabilities=[
        "discord", "channels",
        {"name": "dir", "alias": "data", "config": {"prefix": "data/discord/"}},
        "stdlib", "procs", "file",
    ],
    handlers=["io:discord:dm", "io:discord:mention", "io:discord:message"],
)
