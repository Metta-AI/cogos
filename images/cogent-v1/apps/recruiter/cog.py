from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    capabilities=[
        "me", "procs", "discord", "channels", "secrets",
        "stdlib",
    ],
    handlers=["recruiter:feedback"],
)
