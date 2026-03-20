"""Runtime factory — create the right runtime from a CogtainerEntry."""

from __future__ import annotations

from cogtainer.config import CogtainerEntry
from cogtainer.llm.provider import create_provider
from cogtainer.runtime.base import CogtainerRuntime


def create_runtime(
    entry: CogtainerEntry, cogtainer_name: str = ""
) -> CogtainerRuntime:
    """Instantiate the appropriate runtime for the given cogtainer config."""
    llm = create_provider(entry.llm, region=entry.region or "us-east-1")

    if entry.type in ("local", "docker"):
        from cogtainer.runtime.local import LocalRuntime

        return LocalRuntime(entry=entry, llm=llm)

    if entry.type == "aws":
        from cogtainer.aws import get_aws_session

        from cogtainer.runtime.aws import AwsRuntime

        session, _ = get_aws_session()
        return AwsRuntime(
            entry=entry, llm=llm, session=session, cogtainer_name=cogtainer_name
        )

    raise ValueError(f"Unknown cogtainer type: {entry.type}")


def create_executor_runtime() -> CogtainerRuntime:
    """Reconstruct a runtime inside an executor process from env vars."""
    import os

    cogtainer_type = os.environ.get("COGTAINER", "aws")
    region = os.environ.get("AWS_REGION", "us-east-1")
    llm_provider = os.environ.get("LLM_PROVIDER", "bedrock")

    default_model = os.environ.get(
        "DEFAULT_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )

    llm_config: dict = {"provider": llm_provider, "model": default_model, "api_key_env": ""}
    # Pass through API key env vars for non-bedrock providers
    if llm_provider == "openrouter":
        llm_config["api_key_env"] = "OPENROUTER_API_KEY"
    elif llm_provider == "anthropic":
        llm_config["api_key_env"] = "ANTHROPIC_API_KEY"

    if cogtainer_type in ("local", "docker"):
        from cogtainer.runtime.local import LocalRuntime

        data_dir = os.environ.get(
            "SECRETS_DATA_DIR", os.environ.get("COGOS_LOCAL_DATA", "")
        )
        entry = CogtainerEntry(
            type=cogtainer_type, data_dir=data_dir, region=region, llm=llm_config
        )
        llm = create_provider(entry.llm, region=region)
        return LocalRuntime(entry=entry, llm=llm)

    if cogtainer_type == "aws":
        from cogtainer.runtime.aws import AwsRuntime

        entry = CogtainerEntry(type="aws", region=region, llm=llm_config)
        llm = create_provider(entry.llm, region=region)
        import boto3 as _boto3
        return AwsRuntime(entry=entry, llm=llm, session=_boto3.Session(region_name=region))

    raise ValueError(f"Unknown cogtainer type from env: {cogtainer_type}")
