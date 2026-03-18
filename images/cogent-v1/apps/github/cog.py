from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    priority=2.0,
    executor="python",
    capabilities=[
        "me", "procs", "dir", "file", "github",
        "channels", "stdlib",
    ],
    handlers=[
        "system:tick:hour",
        "github:discover",
    ],
)
