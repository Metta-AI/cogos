from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    executor="python",
    priority=0.5,
    handlers=["process:run:failed", "system:alerts"],
    capabilities=[
        "history", "procs", "channels", "dir", "file", "stdlib", "alerts", "secrets",
    ],
    idle_timeout_ms=60000,
)
