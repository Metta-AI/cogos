"""Dashboard app — delegates to the unified cogos.api.app."""

from cogos.api.app import create_app, app  # noqa: F401

__all__ = ["create_app", "app"]
