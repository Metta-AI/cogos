from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    priority=15.0,
    executor="python",
    capabilities=[
        "me", "procs", "channels", "discord",
        "asana", "github", "google_docs", "email",
        "file", "fs_dir", "secrets", "alerts",
        "cog_registry", "coglet_runtime",
    ],
    handlers=[
        "pointy:daily-tick",
        "pointy:pitch-requested",
        "pointy:feedback-requested",
        "pointy:followup-requested",
    ],
)
