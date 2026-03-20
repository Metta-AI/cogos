"""External service provisioning for cogent creation."""

from __future__ import annotations

import logging
from typing import Any

import requests

from polis.secrets.store import SecretStore

logger = logging.getLogger(__name__)


def provision_ses_email(
    *,
    ses_client: Any,
    store: SecretStore,
    cogent_name: str,
    domain: str,
) -> dict[str, Any]:
    """Create SES email identity for cogent. Returns {"email": "...", "status": "..."}."""
    email = f"{cogent_name}@{domain}"
    try:
        resp = ses_client.get_email_identity(EmailIdentity=email)
        status = resp.get("VerificationStatus", "unknown")
        return {"email": email, "status": status, "created": False}
    except Exception:
        pass
    ses_client.create_email_identity(
        EmailIdentity=email,
        Tags=[
            {"Key": "cogent", "Value": cogent_name},
            {"Key": "managed-by", "Value": "polis"},
        ],
    )
    store.put(f"cogent/{cogent_name}/ses_identity", {"email": email})
    return {"email": email, "status": "pending", "created": True}


def provision_discord_role(
    *,
    store: SecretStore,
    cogent_name: str,
) -> dict[str, Any]:
    """Create a Discord role for the cogent. Returns {"role_id": "...", "role_name": "..."}."""
    discord_config = store.get("polis/discord")
    bot_token = discord_config["bot_token"]
    guild_id = discord_config["guild_id"]
    role_name = f"cogent-{cogent_name}"
    headers = {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}
    resp = requests.get(
        f"https://discord.com/api/v10/guilds/{guild_id}/roles",
        headers=headers,
    )
    resp.raise_for_status()
    for role in resp.json():
        if role["name"] == role_name:
            store.put(
                f"cogent/{cogent_name}/discord_role_id",
                {
                    "role_id": role["id"],
                    "role_name": role_name,
                    "guild_id": guild_id,
                },
            )
            return {"role_id": role["id"], "role_name": role_name, "created": False}
    resp = requests.post(
        f"https://discord.com/api/v10/guilds/{guild_id}/roles",
        headers=headers,
        json={"name": role_name},
    )
    resp.raise_for_status()
    role_data = resp.json()
    store.put(
        f"cogent/{cogent_name}/discord_role_id",
        {
            "role_id": role_data["id"],
            "role_name": role_name,
            "guild_id": guild_id,
        },
    )
    return {"role_id": role_data["id"], "role_name": role_name, "created": True}


def provision_asana_guest(
    *,
    store: SecretStore,
    cogent_name: str,
    domain: str,
) -> dict[str, Any]:
    """Invite cogent email as guest to Asana workspace. Returns {"user_gid": "...", "status": "invited"}."""
    asana_config = store.get("polis/asana")
    access_token = asana_config["access_token"]
    workspace_gid = asana_config["workspace_gid"]
    email = f"{cogent_name}@{domain}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        f"https://app.asana.com/api/1.0/workspaces/{workspace_gid}/addUser",
        headers=headers,
        json={"data": {"user": email}},
    )
    resp.raise_for_status()
    user_data = resp.json()["data"]
    user_gid = user_data["gid"]
    store.put(
        f"cogent/{cogent_name}/asana_user_gid",
        {
            "user_gid": user_gid,
            "email": email,
            "workspace_gid": workspace_gid,
            "status": "invited",
        },
    )
    return {"user_gid": user_gid, "email": email, "status": "invited", "created": True}


def provision_github_credentials(
    *,
    store: SecretStore,
    cogent_name: str,
) -> dict[str, Any]:
    """Copy shared GitHub App credentials to cogent secret. Returns {"type": "...", "created": bool}."""
    target_path = f"cogent/{cogent_name}/github"
    try:
        existing = store.get(target_path, use_cache=False)
        if existing:
            return {"type": existing.get("type", "unknown"), "created": False}
    except Exception:
        pass
    shared = store.get("polis/github_app")
    store.put(target_path, shared)
    return {"type": shared.get("type", "unknown"), "created": True}


def destroy_discord_role(*, store: SecretStore, cogent_name: str) -> None:
    """Delete the cogent's Discord role."""
    discord_config = store.get("polis/discord")
    bot_token = discord_config["bot_token"]
    guild_id = discord_config["guild_id"]
    try:
        role_data = store.get(
            f"cogent/{cogent_name}/discord_role_id", use_cache=False
        )
        role_id = role_data["role_id"]
    except Exception:
        logger.warning("No Discord role found for %s", cogent_name)
        return
    headers = {"Authorization": f"Bot {bot_token}"}
    resp = requests.delete(
        f"https://discord.com/api/v10/guilds/{guild_id}/roles/{role_id}",
        headers=headers,
    )
    resp.raise_for_status()


def destroy_ses_email(*, ses_client: Any, cogent_name: str, domain: str) -> None:
    """Delete the cogent's SES email identity."""
    email = f"{cogent_name}@{domain}"
    ses_client.delete_email_identity(EmailIdentity=email)


def destroy_asana_guest(*, store: SecretStore, cogent_name: str) -> None:
    """Remove the cogent's guest from Asana workspace."""
    asana_config = store.get("polis/asana")
    access_token = asana_config["access_token"]
    try:
        user_data = store.get(
            f"cogent/{cogent_name}/asana_user_gid", use_cache=False
        )
        user_gid = user_data["user_gid"]
        workspace_gid = user_data["workspace_gid"]
    except Exception:
        logger.warning("No Asana user found for %s", cogent_name)
        return
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        f"https://app.asana.com/api/1.0/workspaces/{workspace_gid}/removeUser",
        headers=headers,
        json={"data": {"user": user_gid}},
    )
    resp.raise_for_status()
