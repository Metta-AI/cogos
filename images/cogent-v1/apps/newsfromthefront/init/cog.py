# Newsfromthefront cog — creates the root coglet that orchestrates
# competitive intelligence. Child coglets (researcher, analyst, test,
# backfill) are created at runtime by the orchestrator via cog.make_coglet().

import inspect as _inspect
from pathlib import Path

_THIS_FILE = Path(_inspect.currentframe().f_code.co_filename).resolve()
_APP_DIR = _THIS_FILE.parent.parent


def _read(rel: str) -> str:
    return (_APP_DIR / rel).read_text()


cog = add_cog("newsfromthefront")
cog.make_default_coglet(
    entrypoint="main.md",
    mode="daemon",
    files={"main.md": _read("newsfromthefront.md")},
    capabilities=[
        "me", "procs", "dir", "file", "channels", "discord",
        "web_search", "secrets", "stdlib", "cog", "coglet_runtime",
        {"name": "dir", "alias": "data", "config": {"prefix": "data/newsfromthefront/"}},
    ],
    handlers=[
        "newsfromthefront:tick",
        "newsfromthefront:findings-ready",
        "newsfromthefront:discord-feedback",
        "newsfromthefront:run-requested",
    ],
    priority=15.0,
)
