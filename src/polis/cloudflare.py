"""Cloudflare Access — manage Access Applications and Policies for cogent dashboards."""

from __future__ import annotations

import logging

import requests

from polis.aws import ORG_EMAIL_DOMAIN
from polis.config import deploy_config
from polis.secrets.store import SecretStore

logger = logging.getLogger(__name__)

SECRET_PATH = "cogent/polis/cloudflare"

# Single Access Application protects all cogent dashboards via wildcard.
ACCESS_APP_NAME = "cogent-dashboards"
_EMAIL_POLICY_NAME = deploy_config("cloudflare_email_policy", "allow-softmax")


def _load_cf_config(store: SecretStore) -> dict:
    """Load Cloudflare credentials from Secrets Manager.

    Expected secret structure at cogent/polis/cloudflare:
        {
            "api_token": "...",
            "account_id": "...",
            "zone_id": "..."
        }
    """
    return store.get(SECRET_PATH)


def _headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }


def _find_access_app(account_id: str, api_token: str) -> dict | None:
    """Find existing Access Application by name."""
    resp = requests.get(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps",
        headers=_headers(api_token),
    )
    resp.raise_for_status()
    for app in resp.json().get("result", []):
        if app.get("name") == ACCESS_APP_NAME:
            return app
    return None


def _list_access_policies(account_id: str, app_id: str, api_token: str) -> list[dict]:
    """List policies for an Access Application."""
    resp = requests.get(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app_id}/policies",
        headers=_headers(api_token),
    )
    resp.raise_for_status()
    return resp.json().get("result", [])


def ensure_access(store: SecretStore, domain: str) -> dict:
    """Create or update the Cloudflare Access Application for cogent dashboards.

    Sets up a wildcard self-hosted app for *.{domain} with:
      - Policy: allow org emails (from deploy_config)
      - Policy: allow any valid service token (PAT bypass)
      - Policy: bypass CF Access entirely (dashboard has its own API key auth)

    Returns the Access Application dict.
    """
    cf = _load_cf_config(store)
    account_id = cf["account_id"]
    api_token = cf["api_token"]

    app = _find_access_app(account_id, api_token)

    app_body = {
        "name": ACCESS_APP_NAME,
        "domain": f"*.{domain}",
        "type": "self_hosted",
        "session_duration": "24h",
        "auto_redirect_to_identity": False,
    }

    if app:
        # Update existing
        resp = requests.put(
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app['id']}",
            headers=_headers(api_token),
            json=app_body,
        )
        resp.raise_for_status()
        app = resp.json()["result"]
        logger.info("Updated Access Application: %s", app["id"])
    else:
        # Create new
        resp = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps",
            headers=_headers(api_token),
            json=app_body,
        )
        resp.raise_for_status()
        app = resp.json()["result"]
        logger.info("Created Access Application: %s", app["id"])

    # Ensure policies exist
    _ensure_policies(account_id, app["id"], api_token)

    return app


def _ensure_policies(account_id: str, app_id: str, api_token: str) -> None:
    """Ensure the three required policies exist on the Access Application."""
    existing = _list_access_policies(account_id, app_id, api_token)
    existing_names = {p["name"] for p in existing}

    # Policy 1: allow org emails
    if _EMAIL_POLICY_NAME not in existing_names:
        resp = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app_id}/policies",
            headers=_headers(api_token),
            json={
                "name": _EMAIL_POLICY_NAME,
                "decision": "allow",
                "precedence": 1,
                "include": [{"email_domain": {"domain": ORG_EMAIL_DOMAIN}}],
            },
        )
        resp.raise_for_status()
        logger.info("Created policy: %s", _EMAIL_POLICY_NAME)

    # Policy 2: allow service tokens (PAT bypass)
    if "allow-service-tokens" not in existing_names:
        resp = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app_id}/policies",
            headers=_headers(api_token),
            json={
                "name": "allow-service-tokens",
                "decision": "non_identity",
                "precedence": 2,
                "include": [{"any_valid_service_token": {}}],
            },
        )
        resp.raise_for_status()
        logger.info("Created policy: allow-service-tokens")

    # Policy 3: bypass CF Access entirely — dashboard has its own API key auth
    if "bypass-all" not in existing_names:
        resp = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app_id}/policies",
            headers=_headers(api_token),
            json={
                "name": "bypass-all",
                "decision": "bypass",
                "precedence": 3,
                "include": [{"everyone": {}}],
            },
        )
        resp.raise_for_status()
        logger.info("Created policy: bypass-all")


def ensure_dns_record(
    store: SecretStore,
    subdomain: str,
    target: str,
    domain: str,
) -> dict:
    """Create or update a proxied CNAME record for a cogent subdomain.

    Args:
        subdomain: e.g. "dr-alpha" (without the domain suffix)
        target: ALB DNS name to point to
    """
    cf = _load_cf_config(store)
    zone_id = cf["zone_id"]
    api_token = cf["api_token"]
    fqdn = f"{subdomain}.{domain}"

    # Check if record exists
    resp = requests.get(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
        headers=_headers(api_token),
        params={"name": fqdn, "type": "CNAME"},
    )
    resp.raise_for_status()
    existing = resp.json().get("result", [])

    body = {
        "type": "CNAME",
        "name": subdomain,
        "content": target,
        "proxied": True,
    }

    if existing:
        # Update
        record_id = existing[0]["id"]
        resp = requests.put(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}",
            headers=_headers(api_token),
            json=body,
        )
        resp.raise_for_status()
        logger.info("Updated DNS record: %s -> %s", fqdn, target)
    else:
        # Create
        resp = requests.post(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
            headers=_headers(api_token),
            json=body,
        )
        resp.raise_for_status()
        logger.info("Created DNS record: %s -> %s", fqdn, target)

    return resp.json()["result"]


def delete_dns_record(
    store: SecretStore,
    subdomain: str,
    domain: str,
) -> bool:
    """Delete a Cloudflare DNS record for a cogent subdomain.

    Returns True if deleted, False if not found.
    """
    cf = _load_cf_config(store)
    zone_id = cf["zone_id"]
    api_token = cf["api_token"]
    fqdn = f"{subdomain}.{domain}"

    resp = requests.get(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
        headers=_headers(api_token),
        params={"name": fqdn},
    )
    resp.raise_for_status()
    records = resp.json().get("result", [])

    if not records:
        return False

    for record in records:
        requests.delete(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record['id']}",
            headers=_headers(api_token),
        ).raise_for_status()
        logger.info("Deleted DNS record: %s (%s)", fqdn, record["type"])

    return True


def purge_cache(store: SecretStore) -> None:
    """Purge entire Cloudflare cache for the zone."""
    cf = _load_cf_config(store)
    zone_id = cf["zone_id"]
    api_token = cf["api_token"]

    resp = requests.post(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache",
        headers=_headers(api_token),
        json={"purge_everything": True},
    )
    resp.raise_for_status()
    logger.info("Purged Cloudflare cache for zone %s", zone_id)


def delete_access(store: SecretStore) -> bool:
    """Delete the Cloudflare Access Application (and its policies).

    Returns True if deleted, False if not found.
    """
    cf = _load_cf_config(store)
    account_id = cf["account_id"]
    api_token = cf["api_token"]

    app = _find_access_app(account_id, api_token)
    if not app:
        logger.info("No Access Application found to delete")
        return False

    resp = requests.delete(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app['id']}",
        headers=_headers(api_token),
    )
    resp.raise_for_status()
    logger.info("Deleted Access Application: %s", app["id"])
    return True
