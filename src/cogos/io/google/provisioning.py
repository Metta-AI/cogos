"""GCP service account provisioning for Google integration."""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)

GOOGLE_DOMAIN = "softmax-cogents.com"
ADMIN_SECRET_KEY = "cogtainer/{cogtainer}/google-admin"
ADMIN_EMAIL = "daveey@softmax.com"


def _get_admin_service(secrets_provider: object, service: str = "admin", version: str = "directory_v1"):
    """Build an Admin SDK service using the domain-wide delegation SA."""
    import os

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    cogtainer = os.environ.get("COGTAINER", "")
    key = ADMIN_SECRET_KEY.replace("{cogtainer}", cogtainer) if cogtainer else "cogtainer/shared/google-admin"

    admin_json = json.loads(secrets_provider.get_secret(key))  # type: ignore[union-attr]
    creds = service_account.Credentials.from_service_account_info(
        admin_json,
        scopes=[
            "https://www.googleapis.com/auth/admin.directory.group",
            "https://www.googleapis.com/auth/admin.directory.group.member",
        ],
        subject=admin_json.get("admin_email", ADMIN_EMAIL),
    )
    return build(service, version, credentials=creds, static_discovery=False)


def create_service_account(cogent_name: str, secrets_provider: object) -> str:
    """Create a GCP service account, store its key, and create a Google Group alias.

    Returns the Google Group email (e.g. alpha@softmax-cogents.com).
    """
    import base64

    import google.auth
    from googleapiclient.discovery import build

    credentials, project = google.auth.default()
    if not project:
        raise RuntimeError("Could not determine GCP project from ADC.")

    iam = build("iam", "v1", credentials=credentials, static_discovery=False)

    # SA id must be 6-30 chars, lowercase letters/digits/hyphens
    sa_id = f"cogent-{cogent_name}"
    sa_email = f"{sa_id}@{project}.iam.gserviceaccount.com"

    # Create the service account (idempotent)
    try:
        iam.projects().serviceAccounts().create(
            name=f"projects/{project}",
            body={
                "accountId": sa_id,
                "serviceAccount": {"displayName": f"Cogent {cogent_name}"},
            },
        ).execute()
    except Exception as e:
        if "already exists" in str(e).lower():
            pass
        else:
            raise

    # Create and download a JSON key
    key = (
        iam.projects()
        .serviceAccounts()
        .keys()
        .create(
            name=f"projects/{project}/serviceAccounts/{sa_email}",
            body={"keyAlgorithm": "KEY_ALG_RSA_2048"},
        )
        .execute()
    )

    key_json = base64.b64decode(key["privateKeyData"]).decode()

    # Store in Secrets Manager
    config = json.loads(key_json)
    group_email = f"{cogent_name}@{GOOGLE_DOMAIN}"
    config["service_account_email"] = sa_email
    config["group_email"] = group_email
    secrets_provider.set_secret(f"cogent/{cogent_name}/google", json.dumps(config))  # type: ignore[union-attr]

    # Create Google Group alias
    try:
        _create_group(cogent_name, sa_email, secrets_provider)
    except Exception as e:
        logger.warning("Google Group creation failed (can be retried): %s", e)

    return group_email


def _create_group(cogent_name: str, sa_email: str, secrets_provider: object) -> None:
    """Create a Google Group on GOOGLE_DOMAIN and add the SA as a member."""
    svc = _get_admin_service(secrets_provider)
    group_email = f"{cogent_name}@{GOOGLE_DOMAIN}"

    try:
        svc.groups().insert(body={
            "email": group_email,
            "name": f"Cogent {cogent_name.title()}",
            "description": f"Google sharing alias for cogent {cogent_name}",
        }).execute()
    except Exception as e:
        if "already exists" in str(e).lower():
            pass
        else:
            raise

    # Brief delay for group propagation
    time.sleep(3)

    try:
        svc.members().insert(groupKey=group_email, body={
            "email": sa_email,
            "role": "MEMBER",
        }).execute()
    except Exception as e:
        if "already exists" in str(e).lower() or "member already" in str(e).lower():
            pass
        else:
            raise


def delete_service_account(cogent_name: str, secrets_provider: object) -> None:
    """Delete a GCP service account, its Google Group, and the secret."""
    # Delete Google Group
    try:
        svc = _get_admin_service(secrets_provider)
        svc.groups().delete(groupKey=f"{cogent_name}@{GOOGLE_DOMAIN}").execute()
    except Exception:
        pass

    # Delete GCP service account
    try:
        import google.auth
        from googleapiclient.discovery import build

        credentials, project = google.auth.default()
        if not project:
            return

        sa_id = f"cogent-{cogent_name}"
        sa_email = f"{sa_id}@{project}.iam.gserviceaccount.com"

        iam = build("iam", "v1", credentials=credentials, static_discovery=False)
        iam.projects().serviceAccounts().delete(
            name=f"projects/{project}/serviceAccounts/{sa_email}",
        ).execute()
    except Exception:
        pass

    # Delete secret
    try:
        secrets_provider.delete_secret(f"cogent/{cogent_name}/google")  # type: ignore[union-attr]
    except Exception:
        pass
