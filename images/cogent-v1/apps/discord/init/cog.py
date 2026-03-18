# Discord cog — creates the orchestrator and handler coglets at boot.

import inspect as _inspect
from pathlib import Path

_THIS_FILE = Path(_inspect.currentframe().f_code.co_filename).resolve()
_APP_DIR = _THIS_FILE.parent.parent


def _read(rel: str) -> str:
    return (_APP_DIR / rel).read_text()


cog = add_cog("discord")

# Orchestrator — Python executor, runs health checks with zero LLM tokens.
cog.make_default_coglet(
    entrypoint="main.py",
    mode="daemon",
    executor="python",
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    files={"main.py": _read("discord.py"), "main.md": _read("discord.md")},
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

# Handler — processes Discord messages. Created at boot so it's ready immediately.
cog.make_coglet(
    name="handler",
    entrypoint="main.md",
    mode="daemon",
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    files={
        "main.md": _read("handler/main.md"),
        "test_main.py": _read("handler/test_main.py"),
    },
    capabilities=[
        "discord", "channels", "stdlib", "procs", "file",
        "image", "blob", "secrets", "web",
        {"name": "dir", "alias": "data", "config": {"prefix": "data/discord/"}},
    ],
    handlers=[
        "io:discord:dm",
        "io:discord:mention",
        "io:discord:message",
    ],
    idle_timeout_ms=300000,
)
