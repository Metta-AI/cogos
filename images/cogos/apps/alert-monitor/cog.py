from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    executor="python",
    emoji="\U0001f6a8",
    capabilities=["monitor"],
    handlers=["system:alerts"],
)
