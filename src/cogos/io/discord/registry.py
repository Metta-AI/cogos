"""Read cogent registry from DynamoDB + Secrets Manager for Discord bridge routing."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

import boto3

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
    """Load all cogent configs from DynamoDB + Secrets Manager.

    Reads cogent-status table for DB connection info, and
    cogent/{name}/discord secrets for persona config.
    """
    region = os.environ.get("AWS_REGION", "us-east-1")
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)
    sm = boto3.client("secretsmanager", region_name=region)

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

        db_info = manifest.get("database", {})

        # Read persona config from Secrets Manager
        persona = _read_persona_secret(sm, name)

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


def _read_persona_secret(sm_client, cogent_name: str) -> dict:
    """Read persona config from cogent/{name}/discord secret. Returns empty dict on failure."""
    try:
        resp = sm_client.get_secret_value(SecretId=f"cogent/{cogent_name}/discord")
        data = json.loads(resp["SecretString"])
        return data
    except sm_client.exceptions.ResourceNotFoundException:
        return {}
    except Exception:
        logger.debug("Failed to read discord secret for %s", cogent_name, exc_info=True)
        return {}
