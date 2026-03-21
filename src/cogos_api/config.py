from __future__ import annotations

from pydantic_settings import BaseSettings


class ApiSettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8200
    cors_origins: str = "*"
    cogent_name: str = ""

    # JWT signing — env var for local dev, falls back to Secrets Manager
    jwt_secret: str = ""
    jwt_secret_id: str = "cogtainer/shared/jwt-signing-key"
    jwt_ttl_seconds: int = 3600

    # Executor bootstrap key — env var for local dev, falls back to SM
    executor_key: str = ""
    executor_key_secret_id: str = ""

    model_config = {"env_prefix": "COGOS_API_"}


settings = ApiSettings()
