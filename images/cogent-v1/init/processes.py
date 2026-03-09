add_process(
    "scheduler",
    mode="daemon",
    content="CogOS scheduler daemon",
    code_key="cogos/scheduler",
    runner="lambda",
    priority=100.0,
    capabilities=[
        "scheduler/match_events",
        "scheduler/select_processes",
        "scheduler/dispatch_process",
        "scheduler/unblock_processes",
        "scheduler/kill_process",
    ],
    handlers=["scheduler:tick"],
)
