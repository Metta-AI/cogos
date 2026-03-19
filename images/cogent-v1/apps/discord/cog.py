from cogos.cog.cog import CogConfig, model

config = CogConfig(
    mode="daemon",
    priority=5.0,
    executor="python",
    model=model("haiku"),
    capabilities=[
        "me", "procs", "discord", "channels",
        "stdlib", "image", "blob", "secrets", "web",
    ],
    handlers=[
        "discord-cog:review",
        "system:tick:hour",
    ],
)
