"""GCP service account provisioning for Google integration."""

from __future__ import annotations

GCP_PROJECT = "cogents"  # GCP project ID


def create_service_account(cogent_name: str, secrets_provider: object) -> str:
    """Create a GCP service account and store its key in secrets.

    Uses application default credentials (ADC) to authenticate as the
    admin/infra identity that is allowed to create service accounts.

    Returns the service account email.
    """
    import base64
    import json

    import google.auth
    from googleapiclient.discovery import build

    credentials, _project = google.auth.default()
    iam = build("iam", "v1", credentials=credentials)

    # SA id must be 6-30 chars, lowercase letters/digits/hyphens
    sa_id = f"cogent-{cogent_name}"
    sa_email = f"{sa_id}@{GCP_PROJECT}.iam.gserviceaccount.com"

    # Create the service account (idempotent)
    try:
        iam.projects().serviceAccounts().create(
            name=f"projects/{GCP_PROJECT}",
            body={
                "accountId": sa_id,
                "serviceAccount": {
                    "displayName": f"Cogent {cogent_name}",
                },
            },
        ).execute()
    except Exception as e:
        if "already exists" in str(e).lower():
            pass  # idempotent
        else:
            raise

    # Create and download a JSON key
    key = (
        iam.projects()
        .serviceAccounts()
        .keys()
        .create(
            name=f"projects/{GCP_PROJECT}/serviceAccounts/{sa_email}",
            body={"keyAlgorithm": "KEY_ALG_RSA_2048"},
        )
        .execute()
    )

    # key["privateKeyData"] is base64-encoded JSON
    key_json = base64.b64decode(key["privateKeyData"]).decode()

    # Store in Secrets Manager with the SA email for easy lookup
    config = json.loads(key_json)
    config["service_account_email"] = sa_email
    secrets_provider.set_secret(f"cogent/{cogent_name}/google", json.dumps(config))

    return sa_email


def delete_service_account(cogent_name: str, secrets_provider: object) -> None:
    """Delete a GCP service account and remove its secret."""
    import google.auth
    from googleapiclient.discovery import build

    sa_id = f"cogent-{cogent_name}"
    sa_email = f"{sa_id}@{GCP_PROJECT}.iam.gserviceaccount.com"

    try:
        credentials, _project = google.auth.default()
        iam = build("iam", "v1", credentials=credentials)
        iam.projects().serviceAccounts().delete(
            name=f"projects/{GCP_PROJECT}/serviceAccounts/{sa_email}",
        ).execute()
    except Exception:
        pass  # best-effort cleanup

    try:
        secrets_provider.delete_secret(f"cogent/{cogent_name}/google")
    except Exception:
        pass
