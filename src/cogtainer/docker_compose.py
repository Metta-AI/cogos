"""Generate docker-compose.yml for docker cogtainers."""

from __future__ import annotations

import yaml

from cogtainer.config import CogtainerEntry


def generate_compose(
    entry: CogtainerEntry,
    cogtainer_name: str,
    cogent_names: list[str],
) -> str:
    """Generate a docker-compose.yml string for a docker cogtainer.

    For each cogent, creates two services:
    - dispatcher-{cogent}: runs the local_dispatcher loop
    - dashboard-{cogent}: runs the dashboard web app on port 8080+

    Both services get environment variables for COGENT, USE_LOCAL_DB, LOCAL_DB_DIR,
    LLM_PROVIDER, DEFAULT_MODEL, and optionally the LLM API key from the host.
    """
    services: dict = {}
    base_port = 8080

    for i, cogent_name in enumerate(cogent_names):
        data_dir = entry.data_dir or f"/data/{cogtainer_name}"
        local_db_dir = f"{data_dir}/{cogent_name}"

        env: dict[str, str] = {
            "COGENT": cogent_name,
            "COGTAINER": cogtainer_name,
            "USE_LOCAL_DB": "1",
            "LOCAL_DB_DIR": f"/data/{cogent_name}",
        }

        if entry.llm:
            env["LLM_PROVIDER"] = entry.llm.provider
            env["DEFAULT_MODEL"] = entry.llm.model

        # Dispatcher service
        dispatcher_svc: dict = {
            "image": entry.image or "cogent:latest",
            "command": [
                "python", "-m", "cogtainer.local_dispatcher",
                cogtainer_name, cogent_name,
            ],
            "environment": env.copy(),
            "volumes": [f"{local_db_dir}:/data/{cogent_name}"],
            "restart": "unless-stopped",
        }

        # Pass API key from host if configured
        if entry.llm and entry.llm.api_key_env:
            dispatcher_svc.setdefault("environment", {})[
                entry.llm.api_key_env
            ] = f"${{{entry.llm.api_key_env}}}"

        # Dashboard service
        port = base_port + i
        dashboard_env = env.copy()
        dashboard_svc: dict = {
            "image": entry.image or "cogent:latest",
            "command": [
                "uvicorn", "cogos.api.app:app",
                "--host", "0.0.0.0", "--port", "8080",
            ],
            "environment": dashboard_env,
            "volumes": [f"{local_db_dir}:/data/{cogent_name}"],
            "ports": [f"{port}:8080"],
            "restart": "unless-stopped",
        }

        if entry.llm and entry.llm.api_key_env:
            dashboard_svc.setdefault("environment", {})[
                entry.llm.api_key_env
            ] = f"${{{entry.llm.api_key_env}}}"

        services[f"dispatcher-{cogent_name}"] = dispatcher_svc
        services[f"dashboard-{cogent_name}"] = dashboard_svc

    compose: dict = {
        "version": "3.8",
        "services": services,
    }

    return yaml.dump(compose, default_flow_style=False, sort_keys=False)
