from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    model="us.anthropic.claude-sonnet-4-20250514-v1:0",
    emoji="💬",
    capabilities=[
        "cogent", "discord", "channels", "stdlib", "procs", "file",
        "image", "blob", "secrets", "web",
    ],
    handlers=[
        "io:discord:dm",
        "io:discord:mention",
        "io:discord:message",
    ],
    idle_timeout_ms=300000,
)
