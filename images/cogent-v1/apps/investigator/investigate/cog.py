from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="one_shot",
    executor="llm",
    capabilities=[
        "history", "channels", "dir", "file", "stdlib", "discord", "alerts",
    ],
)
