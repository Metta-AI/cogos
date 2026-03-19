from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    priority=100.0,
    capabilities=[
        "me", "procs", "channels", "discord",
        "web_search", "secrets", "stdlib",
    ],
    handlers=[
        "newsfromthefront:tick",
        "newsfromthefront:findings-ready",
        "newsfromthefront:discord-feedback",
        "newsfromthefront:run-requested",
    ],
)
