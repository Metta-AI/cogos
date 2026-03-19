from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="one_shot",
    emoji="🔧",
    capabilities=[
        "discord", "channels", "stdlib",
        "web_search", "web_fetch", "web", "blob", "image",
        "asana", "email", "github", "secrets",
    ],
)
