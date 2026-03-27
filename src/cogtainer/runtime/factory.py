"""Runtime factory — create the right runtime from a CogtainerEntry."""

from __future__ import annotations

import boto3

from cogtainer.config import CogtainerEntry, LLMConfig
from cogtainer.llm.provider import create_provider
from cogtainer.runtime.base import CogtainerRuntime


def _get_cogtainer_session(entry: CogtainerEntry) -> boto3.Session:
    """Get a boto3 session for the cogtainer's AWS account.

    Uses the configured profile if set, otherwise assumes
    OrganizationAccountAccessRole via the org management account.
    """
    region = entry.region or "us-east-1"

    if entry.profile:
        return boto3.Session(profile_name=entry.profile, region_name=region)

    from cogtainer.cogtainer_cli import resolve_org_profile

    org_session = boto3.Session(
        profile_name=resolve_org_profile(),
        region_name=region,
    )
    sts = org_session.client("sts")
    role_arn = f"arn:aws:iam::{entry.account_id}:role/OrganizationAccountAccessRole"
    resp = sts.assume_role(RoleArn=role_arn, RoleSessionName="cogtainer-cli")
    creds = resp["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )


def create_runtime(entry: CogtainerEntry, cogtainer_name: str = "") -> CogtainerRuntime:
    """Instantiate the appropriate runtime for the given cogtainer config."""
    llm = create_provider(entry.llm, region=entry.region or "us-east-1")

    if entry.type in ("local", "docker"):
        from cogtainer.runtime.local import LocalRuntime

        return LocalRuntime(entry=entry, llm=llm)

    if entry.type == "aws":
        from cogtainer.runtime.aws import AwsRuntime

        session = _get_cogtainer_session(entry)
        return AwsRuntime(entry=entry, llm=llm, session=session, cogtainer_name=cogtainer_name)

    raise ValueError(f"Unknown cogtainer type: {entry.type}")


def create_executor_runtime() -> CogtainerRuntime:
    """Reconstruct a runtime inside an executor process from env vars.

    Resolves the cogtainer type by looking up the COGTAINER name in the config.
    Falls back to env-var-based construction for Lambda environments where
    the config file is unavailable.
    """
    import os

    cogtainer_name = os.environ["COGTAINER"]
    region = os.environ.get("AWS_REGION", "us-east-1")
    llm_provider = os.environ.get("LLM_PROVIDER", "bedrock")
    default_model = os.environ.get("DEFAULT_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")

    # Try to resolve type from config; fall back to env-based detection for
    # executor subprocesses and Lambda environments where the config file
    # is unavailable or the COGTAINER value is a type rather than a name.
    cogtainer_type = None
    try:
        from cogtainer.config import load_config

        cfg = load_config()
        entry = cfg.cogtainers[cogtainer_name]
        cogtainer_type = entry.type
    except Exception:
        pass

    if cogtainer_type is None:
        if cogtainer_name in ("local", "docker"):
            cogtainer_type = cogtainer_name
        else:
            cogtainer_type = "aws"

    llm_config = LLMConfig(provider=llm_provider, model=default_model, api_key_env="")
    if llm_provider == "openrouter":
        llm_config.api_key_env = "OPENROUTER_API_KEY"
    elif llm_provider == "anthropic":
        llm_config.api_key_env = "ANTHROPIC_API_KEY"

    if cogtainer_type in ("local", "docker"):
        from cogtainer.runtime.local import LocalRuntime

        entry = CogtainerEntry(type=cogtainer_type, region=region, llm=llm_config)
        llm = create_provider(entry.llm, region=region)
        return LocalRuntime(entry=entry, llm=llm)

    if cogtainer_type == "aws":
        from cogtainer.runtime.aws import AwsRuntime

        entry = CogtainerEntry(type="aws", region=region, llm=llm_config)
        llm = create_provider(entry.llm, region=region)
        import boto3 as _boto3

        return AwsRuntime(
            entry=entry,
            llm=llm,
            session=_boto3.Session(region_name=region),
            cogtainer_name=cogtainer_name,
        )

    raise ValueError(f"Unknown cogtainer type: {cogtainer_type}")
