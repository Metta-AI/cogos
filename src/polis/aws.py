"""AWS helpers for polis account operations."""

from __future__ import annotations

import logging
import os
import time

import boto3

logger = logging.getLogger(__name__)

POLIS_ACCOUNT_NAME = "cogent-polis"
POLIS_ACCOUNT_ID = "901289084804"
DEFAULT_REGION = "us-east-1"

# Module-level profile override, set by CLI --profile
_profile: str | None = None


def set_profile(profile: str | None) -> None:
    """Set the AWS profile used for org-level operations."""
    global _profile
    _profile = profile


def get_org_session() -> boto3.Session:
    """Return a session for the management account."""
    return boto3.Session(profile_name=_profile, region_name=DEFAULT_REGION)


def get_org_id(session: boto3.Session | None = None) -> str:
    """Get the AWS Organization ID."""
    session = session or get_org_session()
    org = session.client("organizations")
    return org.describe_organization()["Organization"]["Id"]


def find_polis_account(session: boto3.Session | None = None) -> str | None:
    """Find the polis account ID in the org."""
    session = session or get_org_session()
    org = session.client("organizations")
    paginator = org.get_paginator("list_accounts")
    for page in paginator.paginate():
        for acct in page["Accounts"]:
            if acct["Name"] == POLIS_ACCOUNT_NAME and acct["Status"] == "ACTIVE":
                return acct["Id"]
    return None


def create_polis_account(session: boto3.Session | None = None) -> str:
    """Create the cogent-polis org account. Returns account ID."""
    session = session or get_org_session()
    org = session.client("organizations")
    tag = os.urandom(3).hex()
    email = f"cogent-polis+{tag}@softmax.com"

    resp = org.create_account(Email=email, AccountName=POLIS_ACCOUNT_NAME)
    request_id = resp["CreateAccountStatus"]["Id"]

    while True:
        status = org.describe_create_account_status(
            CreateAccountRequestId=request_id,
        )["CreateAccountStatus"]
        state = status["State"]
        if state == "SUCCEEDED":
            return status["AccountId"]
        if state == "FAILED":
            reason = status.get("FailureReason", "unknown")
            if reason == "EMAIL_ALREADY_EXISTS":
                tag = os.urandom(3).hex()
                email = f"cogent-polis+{tag}@softmax.com"
                resp = org.create_account(Email=email, AccountName=POLIS_ACCOUNT_NAME)
                request_id = resp["CreateAccountStatus"]["Id"]
                continue
            raise RuntimeError(f"Account creation failed: {reason}")
        logger.info("Account creation: %s", state)
        time.sleep(5)


def get_polis_session(session: boto3.Session | None = None) -> tuple[boto3.Session, str]:
    """Assume a role into the polis account. Returns (session, account_id)."""
    session = session or get_org_session()
    account_id = POLIS_ACCOUNT_ID

    # Try cogent-polis-admin (works from any account in the org)
    try:
        return _assume_role(session, account_id, "cogent-polis-admin"), account_id
    except Exception:
        pass

    # Fall back to OrganizationAccountAccessRole (management account only)
    try:
        return _assume_role(session, account_id, "OrganizationAccountAccessRole"), account_id
    except Exception:
        pass

    raise ValueError(
        f"Cannot assume into polis account {account_id}. "
        "Ensure your AWS profile has permission to assume cogent-polis-admin."
    )


def _assume_role(session: boto3.Session, account_id: str, role_name: str) -> boto3.Session:
    """Assume a role in the given account."""
    sts = session.client("sts")
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    resp = sts.assume_role(RoleArn=role_arn, RoleSessionName="polis-cli")
    creds = resp["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=DEFAULT_REGION,
    )
