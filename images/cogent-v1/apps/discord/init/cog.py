# Discord cog — creates the root coglet that orchestrates Discord.
# The handler child coglet (message dispatch) is created at runtime
# by the orchestrator via cog.make_coglet().

import inspect as _inspect
from pathlib import Path

_THIS_FILE = Path(_inspect.currentframe().f_code.co_filename).resolve()
_APP_DIR = _THIS_FILE.parent.parent


def _read(rel: str) -> str:
    return (_APP_DIR / rel).read_text()


cog = add_cog("discord")
cog.make_default_coglet(
    entrypoint="main.md",
    mode="daemon",
    files={"main.md": _read("discord.md")},
    capabilities=[
        "me", "procs", "dir", "file", "discord", "channels",
        "stdlib", "cog", "coglet_runtime", "image", "blob", "secrets", "web",
        {"name": "dir", "alias": "data", "config": {"prefix": "data/discord/"}},
    ],
    handlers=[
        "discord-cog:review",
        "system:tick:hour",
    ],
    priority=5.0,
)
