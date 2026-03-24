"""GCP service account provisioning for Google integration."""

from __future__ import annotations


def _get_project() -> str:
    """Discover the GCP project from application default credentials."""
    import google.auth

    _credentials, project = google.auth.default()
    if not project:
        raise RuntimeError(
            "Could not determine GCP project from application default credentials. "
            "Set a quota project via `gcloud auth application-default set-quota-project <PROJECT>`."
        )
    return project


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

    credentials, project = google.auth.default()
    if not project:
        raise RuntimeError("Could not determine GCP project from ADC.")

    iam = build("iam", "v1", credentials=credentials)

    # SA id must be 6-30 chars, lowercase letters/digits/hyphens
    sa_id = f"cogent-{cogent_name}"
    sa_email = f"{sa_id}@{project}.iam.gserviceaccount.com"

    # Create the service account (idempotent)
    try:
        iam.projects().serviceAccounts().create(
            name=f"projects/{project}",
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
            name=f"projects/{project}/serviceAccounts/{sa_email}",
            body={"keyAlgorithm": "KEY_ALG_RSA_2048"},
        )
        .execute()
    )

    # key["privateKeyData"] is base64-encoded JSON
    key_json = base64.b64decode(key["privateKeyData"]).decode()

    # Store in Secrets Manager with the SA email for easy lookup
    config = json.loads(key_json)
    config["service_account_email"] = sa_email
    secrets_provider.set_secret(f"cogent/{cogent_name}/google", json.dumps(config))  # type: ignore[union-attr]

    return sa_email


def delete_service_account(cogent_name: str, secrets_provider: object) -> None:
    """Delete a GCP service account and remove its secret."""
    try:
        import google.auth
        from googleapiclient.discovery import build

        credentials, project = google.auth.default()
        if not project:
            return

        sa_id = f"cogent-{cogent_name}"
        sa_email = f"{sa_id}@{project}.iam.gserviceaccount.com"

        iam = build("iam", "v1", credentials=credentials)
        iam.projects().serviceAccounts().delete(
            name=f"projects/{project}/serviceAccounts/{sa_email}",
        ).execute()
    except Exception:
        pass  # best-effort cleanup

    try:
        secrets_provider.delete_secret(f"cogent/{cogent_name}/google")  # type: ignore[union-attr]
    except Exception:
        pass
