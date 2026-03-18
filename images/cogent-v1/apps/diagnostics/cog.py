from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="one_shot",
    executor="python",
    priority=1.0,
    capabilities=[
        "me", "procs", "dir", "file",
        "channels", "scheduler", "stdlib",
        "discord", "email", "asana", "github",
        "web", "web_search", "web_fetch",
        "blob", "image", "alerts",
    ],
)
