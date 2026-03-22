"""Dashboard DB — delegates to cogos.api.db for unified repository access."""

from cogos.api.db import get_repo  # noqa: F401

__all__ = ["get_repo"]
