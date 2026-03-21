"""Legacy CLI entry point — redirects to cogos.cli.__main__."""

# Backward compat: some modules import from cli.__main__
from cogos.cli.__main__ import cogos as main  # noqa: F401
from cogos.cli.__main__ import entry

if __name__ == "__main__":
    entry()
