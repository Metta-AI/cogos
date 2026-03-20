"""AWS helpers for cogtainer account operations."""

from __future__ import annotations

import logging
import os

import boto3

from cogtainer.deploy_config import deploy_config

logger = logging.getLogger(__name__)

ACCOUNT_NAME = deploy_config("account_name", "")
ACCOUNT_ID = deploy_config("account_id", "")
DEFAULT_REGION = deploy_config("region", "us-east-1")
DEFAULT_ORG_PROFILE = deploy_config("org_profile", "softmax-org")
ORG_PROFILE_ENV = "COGENT_ORG_PROFILE"
ORG_EMAIL_DOMAIN = deploy_config("org_email_domain", "softmax.com")

# Module-level profile override, set by CLI --profile
_profile: str | None = None


def set_profile(profile: str | None) -> None:
    """Set the AWS profile used for org-level operations."""
    global _profile
    _profile = profile


def resolve_org_profile(profile: str | None = None) -> str:
    """Resolve the org-admin AWS profile for cogtainer-targeting operations."""
    for candidate in (profile, os.getenv(ORG_PROFILE_ENV)):
        if candidate:
            cleaned = candidate.strip()
            if cleaned:
                return cleaned
    return DEFAULT_ORG_PROFILE


def set_org_profile(profile: str | None = None) -> str:
    """Resolve and store the AWS profile used for org-level operations."""
    resolved = resolve_org_profile(profile)
    set_profile(resolved)
    return resolved


def get_org_session() -> boto3.Session:
    """Return a session for the management account."""
    return boto3.Session(profile_name=_profile, region_name=DEFAULT_REGION)


def get_org_id(session: boto3.Session | None = None) -> str:
    """Get the AWS Organization ID."""
    session = session or get_org_session()
    org = session.client("organizations")
    return org.describe_organization()["Organization"]["Id"]


def get_aws_session(session: boto3.Session | None = None) -> tuple[boto3.Session, str]:
    """Assume a role into the cogtainer account. Returns (session, account_id)."""
    session = session or get_org_session()
    account_id = ACCOUNT_ID

    # Try {account_name}-admin (works from any account in the org)
    try:
        return _assume_role(session, account_id, f"{ACCOUNT_NAME}-admin"), account_id
    except Exception:
        pass

    # Fall back to OrganizationAccountAccessRole (management account only)
    try:
        return _assume_role(session, account_id, "OrganizationAccountAccessRole"), account_id
    except Exception:
        pass

    raise ValueError(
        f"Cannot assume into cogtainer account {account_id}. "
        f"Ensure your AWS profile has permission to assume {ACCOUNT_NAME}-admin."
    )


def _assume_role(session: boto3.Session, account_id: str, role_name: str) -> boto3.Session:
    """Assume a role in the given account."""
    sts = session.client("sts")
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    resp = sts.assume_role(RoleArn=role_arn, RoleSessionName="cogtainer-cli")
    creds = resp["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=DEFAULT_REGION,
    )
