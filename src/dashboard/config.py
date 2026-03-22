"""Dashboard config — delegates to cogos.api.config for unified settings."""

from cogos.api.config import DashboardSettings, dashboard_settings as settings  # noqa: F401

__all__ = ["DashboardSettings", "settings"]
