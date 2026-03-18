from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    emoji="💬",
    capabilities=[
        "discord", "channels", "stdlib", "procs", "file",
        "image", "blob", "secrets", "web",
    ],
    handlers=[
        "io:discord:dm",
        "io:discord:mention",
        "io:discord:message",
    ],
    idle_timeout_ms=300000,
)
