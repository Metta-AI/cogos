"""Read cogent registry from DynamoDB + secrets provider for Discord bridge routing."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

import boto3

from cogos.capabilities._secrets_helper import fetch_secret

logger = logging.getLogger(__name__)

DYNAMO_TABLE = os.environ.get("DYNAMO_TABLE", "cogent-status")


@dataclass
class CogentDiscordConfig:
    """Discord configuration for a single cogent."""
    cogent_name: str
    display_name: str = ""
    avatar_url: str = ""
    color: int = 0
    default_channels: list[str] = field(default_factory=list)
    db_resource_arn: str = ""
    db_secret_arn: str = ""
    db_name: str = "cogent"

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.cogent_name


def load_cogent_configs(table_name: str = DYNAMO_TABLE) -> list[CogentDiscordConfig]:
    """Load all cogent configs from DynamoDB + secrets provider.

    Reads cogent-status table for DB connection info, and
    cogent/{name}/discord secrets for persona config.
    """
    region = os.environ.get("AWS_REGION", "us-east-1")
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    items = table.scan().get("Items", [])
    configs = []

    for item in items:
        name = item.get("cogent_name", "")
        if not name:
            continue

        # Parse status manifest for DB info
        manifest_raw = item.get("status_manifest", "{}")
        if isinstance(manifest_raw, str):
            try:
                manifest = json.loads(manifest_raw)
            except Exception:
                manifest = {}
        else:
            manifest = manifest_raw

        # DB info: check top-level item first, then manifest
        db_info = item.get("database") or manifest.get("database") or {}

        # Read persona config from secrets provider
        persona = _read_persona_secret(name)

        configs.append(CogentDiscordConfig(
            cogent_name=name,
            display_name=persona.get("display_name", name),
            avatar_url=persona.get("avatar_url", ""),
            color=int(persona.get("color", 0)),
            default_channels=[str(c) for c in persona.get("default_channels", [])],
            db_resource_arn=db_info.get("cluster_arn", ""),
            db_secret_arn=db_info.get("secret_arn", ""),
            db_name=db_info.get("db_name", "cogent"),
        ))

    logger.info("Loaded %d cogent configs from %s", len(configs), table_name)
    return configs


def _read_persona_secret(cogent_name: str) -> dict:
    """Read persona config from cogent/{name}/discord secret. Returns empty dict on failure."""
    try:
        raw = fetch_secret(f"cogent/{cogent_name}/discord")
        return json.loads(raw)
    except (RuntimeError, KeyError):
        return {}
    except Exception:
        logger.debug("Failed to read discord secret for %s", cogent_name, exc_info=True)
        return {}
