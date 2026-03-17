import inspect as _inspect
from pathlib import Path

_THIS_FILE = Path(_inspect.currentframe().f_code.co_filename).resolve()
_APP_DIR = _THIS_FILE.parent.parent


def _read(rel: str) -> str:
    return (_APP_DIR / rel).read_text()


cog = add_cog("website")
cog.make_default_coglet(
    entrypoint="main.py",
    mode="daemon",
    executor="python",
    files={"main.py": _read("handler/main.py")},
    capabilities=[
        "me", "procs", "dir", "file", "web", "channels",
        "stdlib",
        {"name": "dir", "alias": "data", "config": {"prefix": "data/"}},
    ],
    handlers=["io:web:request"],
    priority=5.0,
)
