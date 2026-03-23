"""Cloudflare Access — manage Access Applications and Policies for cogent dashboards."""

from __future__ import annotations

import logging

import requests

# Default timeout for all Cloudflare API calls (connect, read) in seconds.
# Applied via a shared session to avoid repeating timeout= on every call.
_TIMEOUT = (10, 30)


class _TimeoutSession(requests.Session):
    """requests.Session that applies a default timeout to all requests."""

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", _TIMEOUT)
        return super().request(method, url, **kwargs)


requests = _TimeoutSession()  # type: ignore[assignment]

from cogtainer.aws import ORG_EMAIL_DOMAIN
from cogtainer.deploy_config import deploy_config
from cogtainer.secret_store import SecretStore

logger = logging.getLogger(__name__)

from cogtainer.secrets import cogtainer_key

# Single Access Application protects all cogent dashboards via wildcard.
ACCESS_APP_NAME = "cogent-dashboards"
_EMAIL_POLICY_NAME = deploy_config("cloudflare_email_policy", "allow-softmax")


def _load_cf_config(store: SecretStore) -> dict:
    """Load Cloudflare credentials from Secrets Manager.

    Expected secret structure at cogtainer/{COGTAINER}/cloudflare:
        {
            "api_token": "...",
            "account_id": "...",
            "zone_id": "..."
        }
    """
    return store.get(cogtainer_key("cloudflare"))


def _headers(cf: dict) -> dict[str, str]:
    """Build Cloudflare API headers, supporting both api_token and api_key/email."""
    if "api_token" in cf:
        return {
            "Authorization": f"Bearer {cf['api_token']}",
            "Content-Type": "application/json",
        }
    # Legacy: Global API Key + email
    return {
        "X-Auth-Email": cf["email"],
        "X-Auth-Key": cf["api_key"],
        "Content-Type": "application/json",
    }


def _find_access_app(account_id: str, cf: dict) -> dict | None:
    """Find existing Access Application by name."""
    resp = requests.get(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps",
        headers=_headers(cf),
    )
    resp.raise_for_status()
    for app in resp.json().get("result", []):
        if app.get("name") == ACCESS_APP_NAME:
            return app
    return None


def _list_access_policies(account_id: str, app_id: str, cf: dict) -> list[dict]:
    """List policies for an Access Application."""
    resp = requests.get(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app_id}/policies",
        headers=_headers(cf),
    )
    resp.raise_for_status()
    return resp.json().get("result", [])


def ensure_access(store: SecretStore, domain: str) -> dict:
    """Create or update the Cloudflare Access Application for cogent dashboards."""
    cf = _load_cf_config(store)
    account_id = cf["account_id"]


    app = _find_access_app(account_id, cf)

    app_body = {
        "name": ACCESS_APP_NAME,
        "domain": f"*.{domain}",
        "type": "self_hosted",
        "session_duration": "24h",
        "auto_redirect_to_identity": False,
    }

    if app:
        resp = requests.put(
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app['id']}",
            headers=_headers(cf),
            json=app_body,
        )
        resp.raise_for_status()
        app = resp.json()["result"]
        logger.info("Updated Access Application: %s", app["id"])
    else:
        resp = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps",
            headers=_headers(cf),
            json=app_body,
        )
        resp.raise_for_status()
        app = resp.json()["result"]
        logger.info("Created Access Application: %s", app["id"])

    _ensure_policies(account_id, app["id"], cf)
    return app


def _ensure_policies(account_id: str, app_id: str, cf: dict) -> None:
    """Ensure the three required policies exist on the Access Application."""
    existing = _list_access_policies(account_id, app_id, cf)
    existing_names = {p["name"] for p in existing}

    if _EMAIL_POLICY_NAME not in existing_names:
        resp = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app_id}/policies",
            headers=_headers(cf),
            json={
                "name": _EMAIL_POLICY_NAME,
                "decision": "allow",
                "precedence": 1,
                "include": [{"email_domain": {"domain": ORG_EMAIL_DOMAIN}}],
            },
        )
        resp.raise_for_status()
        logger.info("Created policy: %s", _EMAIL_POLICY_NAME)

    if "allow-service-tokens" not in existing_names:
        resp = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app_id}/policies",
            headers=_headers(cf),
            json={
                "name": "allow-service-tokens",
                "decision": "non_identity",
                "precedence": 2,
                "include": [{"any_valid_service_token": {}}],
            },
        )
        resp.raise_for_status()
        logger.info("Created policy: allow-service-tokens")

    if "bypass-all" not in existing_names:
        resp = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app_id}/policies",
            headers=_headers(cf),
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
    """Create or update a proxied CNAME record for a cogent subdomain."""
    cf = _load_cf_config(store)
    zone_id = cf["zone_id"]

    fqdn = f"{subdomain}.{domain}"

    resp = requests.get(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
        headers=_headers(cf),
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
        record_id = existing[0]["id"]
        resp = requests.put(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}",
            headers=_headers(cf),
            json=body,
        )
        resp.raise_for_status()
        logger.info("Updated DNS record: %s -> %s", fqdn, target)
    else:
        resp = requests.post(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
            headers=_headers(cf),
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
    """Delete a Cloudflare DNS record for a cogent subdomain."""
    cf = _load_cf_config(store)
    zone_id = cf["zone_id"]

    fqdn = f"{subdomain}.{domain}"

    resp = requests.get(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
        headers=_headers(cf),
        params={"name": fqdn},
    )
    resp.raise_for_status()
    records = resp.json().get("result", [])

    if not records:
        return False

    for record in records:
        requests.delete(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record['id']}",
            headers=_headers(cf),
        ).raise_for_status()
        logger.info("Deleted DNS record: %s (%s)", fqdn, record["type"])

    return True


def ensure_dns_record_unproxied(
    store: SecretStore,
    name: str,
    target: str,
    domain: str,
    record_type: str = "CNAME",
) -> dict:
    """Create or update an unproxied DNS record (e.g. for ACM validation)."""
    cf = _load_cf_config(store)
    zone_id = cf["zone_id"]

    fqdn = f"{name}.{domain}" if not name.endswith(domain) else name

    resp = requests.get(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
        headers=_headers(cf),
        params={"name": fqdn, "type": record_type},
    )
    resp.raise_for_status()
    existing = resp.json().get("result", [])

    body = {
        "type": record_type,
        "name": fqdn,
        "content": target,
        "proxied": False,
    }

    if existing:
        record_id = existing[0]["id"]
        resp = requests.put(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}",
            headers=_headers(cf),
            json=body,
        )
        resp.raise_for_status()
        logger.info("Updated unproxied DNS record: %s -> %s", fqdn, target)
    else:
        resp = requests.post(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
            headers=_headers(cf),
            json=body,
        )
        resp.raise_for_status()
        logger.info("Created unproxied DNS record: %s -> %s", fqdn, target)

    return resp.json()["result"]


def list_dns_records(store: SecretStore) -> list[dict]:
    """List all DNS records in the Cloudflare zone."""
    cf = _load_cf_config(store)
    zone_id = cf["zone_id"]


    records: list[dict] = []
    page = 1
    while True:
        resp = requests.get(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
            headers=_headers(cf),
            params={"page": page, "per_page": 100},
        )
        resp.raise_for_status()
        data = resp.json()
        records.extend(data.get("result", []))
        if page >= data.get("result_info", {}).get("total_pages", 1):
            break
        page += 1

    return records


def purge_cache(store: SecretStore) -> None:
    """Purge entire Cloudflare cache for the zone."""
    cf = _load_cf_config(store)
    zone_id = cf["zone_id"]


    resp = requests.post(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache",
        headers=_headers(cf),
        json={"purge_everything": True},
    )
    resp.raise_for_status()
    logger.info("Purged Cloudflare cache for zone %s", zone_id)


def delete_access(store: SecretStore) -> bool:
    """Delete the Cloudflare Access Application (and its policies)."""
    cf = _load_cf_config(store)
    account_id = cf["account_id"]


    app = _find_access_app(account_id, cf)
    if not app:
        logger.info("No Access Application found to delete")
        return False

    resp = requests.delete(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/access/apps/{app['id']}",
        headers=_headers(cf),
    )
    resp.raise_for_status()
    logger.info("Deleted Access Application: %s", app["id"])
    return True
