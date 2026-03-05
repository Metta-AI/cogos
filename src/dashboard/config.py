from __future__ import annotations

from pydantic_settings import BaseSettings


class DashboardSettings(BaseSettings):
    database_url: str = "postgresql://cogent:cogent_dev@localhost:5432/cogent"
    host: str = "0.0.0.0"
    port: int = 8100
    cors_origins: str = "*"
    cogent_name: str = ""

    model_config = {"env_prefix": "DASHBOARD_"}


settings = DashboardSettings()
