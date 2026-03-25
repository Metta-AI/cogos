"""Dashboard config — delegates to cogos.api.config for unified settings."""

from cogos.api.config import DashboardSettings  # noqa: F401
from cogos.api.config import dashboard_settings as settings

__all__ = ["DashboardSettings", "settings"]
