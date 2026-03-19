from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="one_shot",
    executor="llm",
    capabilities=[
        "history", "channels", "stdlib", "discord", "alerts",
    ],
)
