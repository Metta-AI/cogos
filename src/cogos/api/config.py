from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings


class ApiSettings(BaseSettings):
    """CogOS API settings (COGOS_API_ prefix).

    Required for production:
        - jwt_secret OR jwt_secret_id (for signing JWT tokens)
        - executor_key OR executor_key_secret_id (for executor bootstrap)
        - cors_origins (set to actual dashboard domain)
    """

    host: str = "0.0.0.0"
    port: int = 8200
    cors_origins: str = "http://localhost:5174,http://localhost:8100"
    cogent_name: str = ""

    # JWT signing — env var for local dev, falls back to Secrets Manager
    jwt_secret: str = ""
    jwt_secret_id: str = "cogtainer/shared/jwt-signing-key"
    jwt_ttl_seconds: int = 3600

    # Executor bootstrap key — env var for local dev, falls back to SM
    executor_key: str = ""
    executor_key_secret_id: str = ""

    model_config = {"env_prefix": "COGOS_API_"}

    @field_validator("jwt_ttl_seconds")
    @classmethod
    def _validate_ttl(cls, v: int) -> int:
        if v < 60 or v > 86400:
            raise ValueError("jwt_ttl_seconds must be between 60 and 86400")
        return v


class DashboardSettings(BaseSettings):
    """Dashboard-specific settings (DASHBOARD_ prefix)."""

    host: str = "0.0.0.0"
    port: int = 8100
    cors_origins: str = "http://localhost:5174,http://localhost:8100"
    cogent_name: str = ""

    model_config = {"env_prefix": "DASHBOARD_"}


settings = ApiSettings()
dashboard_settings = DashboardSettings()
