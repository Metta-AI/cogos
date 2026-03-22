"""Email provisioning — Cloudflare routing rules + SES identity verification.

Moved from cogos.io.email.provision into cogtainer since this is
infrastructure provisioning, not cogent runtime code.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from cogtainer.runtime.base import CogtainerRuntime

logger = logging.getLogger(__name__)

_DEFAULT_DOMAIN = os.environ.get("EMAIL_DOMAIN", "softmax-cogents.com")


def _cf_headers() -> dict[str, str]:
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if not api_token:
        raise RuntimeError("CLOUDFLARE_API_TOKEN not set")
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }


def _cf_zone_id() -> str:
    zone_id = os.environ.get("CLOUDFLARE_ZONE_ID", "")
    if not zone_id:
        raise RuntimeError("CLOUDFLARE_ZONE_ID not set")
    return zone_id


def _cf_account_id() -> str:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    if not account_id:
        raise RuntimeError("CLOUDFLARE_ACCOUNT_ID not set")
    return account_id


def _kv_namespace_id() -> str:
    ns_id = os.environ.get("CLOUDFLARE_KV_NAMESPACE_ID", "")
    if not ns_id:
        raise RuntimeError("CLOUDFLARE_KV_NAMESPACE_ID not set")
    return ns_id


def create_email_route(
    cogent_name: str,
    domain: str = _DEFAULT_DOMAIN,
) -> dict:
    """Create a Cloudflare Email Routing rule for a cogent.

    Creates a rule that matches <cogent_name>@<domain> and routes to
    the email worker.
    """
    zone_id = _cf_zone_id()
    address = f"{cogent_name}@{domain}"

    resp = requests.post(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/email/routing/rules",
        headers=_cf_headers(),
        json={
            "name": f"cogent-{cogent_name}",
            "enabled": True,
            "matchers": [{"type": "literal", "field": "to", "value": address}],
            "actions": [{"type": "worker", "value": ["cogent-email-worker"]}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()
    logger.info("Created CF email routing rule for %s: %s", address, result.get("result", {}).get("id"))
    return result


def set_kv_route(
    cogent_name: str,
    ingest_url: str,
) -> None:
    """Set a KV entry mapping cogent name to its ingest URL."""
    account_id = _cf_account_id()
    ns_id = _kv_namespace_id()

    resp = requests.put(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/storage/kv/namespaces/{ns_id}/values/{cogent_name}",
        headers=_cf_headers(),
        data=ingest_url,
        timeout=30,
    )
    resp.raise_for_status()
    logger.info("Set KV route: %s -> %s", cogent_name, ingest_url)


def verify_ses_email(
    cogent_name: str,
    domain: str = _DEFAULT_DOMAIN,
    region: str = "us-east-1",
    *,
    runtime: CogtainerRuntime,
) -> dict:
    """Verify a cogent's email identity in SES.

    For domain-verified SES, individual addresses don't need separate
    verification. This is a no-op if the domain is already verified,
    but we call it to confirm.
    """
    address = f"{cogent_name}@{domain}"

    verified = runtime.verify_email_domain(domain)
    if verified:
        logger.info("Domain %s already verified, %s can send", domain, address)
        return {"address": address, "domain_verified": True}
    logger.warning("Domain %s not verified. Run domain verification first.", domain)
    return {"address": address, "domain_verified": False}


def provision_email(
    cogent_name: str,
    domain: str = _DEFAULT_DOMAIN,
    region: str = "us-east-1",
    *,
    runtime: CogtainerRuntime,
) -> dict:
    """Full provisioning: CF routing rule + KV entry + SES check."""
    ingest_url = f"https://{cogent_name}.{domain}/api/ingest/email"

    cf_result = create_email_route(cogent_name, domain)
    set_kv_route(cogent_name, ingest_url)
    ses_result = verify_ses_email(cogent_name, domain, region, runtime=runtime)

    return {
        "address": f"{cogent_name}@{domain}",
        "ingest_url": ingest_url,
        "cf_rule_id": cf_result.get("result", {}).get("id"),
        "ses_verified": ses_result.get("domain_verified", False),
    }
