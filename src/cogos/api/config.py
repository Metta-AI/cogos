from __future__ import annotations

from pydantic_settings import BaseSettings


class ApiSettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8200
    cors_origins: str = "http://localhost:5174,http://localhost:8100"
    cogent_name: str = ""

    model_config = {"env_prefix": "COGOS_API_"}


class DashboardSettings(BaseSettings):
    """Dashboard-specific settings (DASHBOARD_ prefix)."""

    host: str = "0.0.0.0"
    port: int = 8100
    cors_origins: str = "http://localhost:5174,http://localhost:8100"
    cogent_name: str = ""

    model_config = {"env_prefix": "DASHBOARD_"}


settings = ApiSettings()
dashboard_settings = DashboardSettings()
