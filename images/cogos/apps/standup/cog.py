from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    priority=100.0,
    executor="llm",
    capabilities=[
        "me", "procs", "channels", "discord",
        "asana", "github", "secrets",
    ],
    handlers=[
        "standup:tick",
    ],
)
