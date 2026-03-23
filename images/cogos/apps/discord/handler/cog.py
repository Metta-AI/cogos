from cogos.cog.cog import CogConfig, model

config = CogConfig(
    mode="daemon",
    model=model("sonnet"),
    emoji="💬",
    capabilities=[
        "discord", "channels",
        "image", "blob", "secrets", "web",
    ],
    handlers=[
        "io:discord:dm",
        "io:discord:mention",
        "io:discord:message",
    ],
    idle_timeout_ms=300000,
)
