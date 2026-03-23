"""Dashboard API router for integration management."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cogos.io.integration import INTEGRATIONS, INTEGRATIONS_BY_NAME
from cogtainer.secrets import AwsSecretsProvider

logger = logging.getLogger(__name__)

router = APIRouter(tags=["integrations"])


def _get_secrets_provider():
    return AwsSecretsProvider(region=os.environ.get("AWS_REGION", "us-east-1"))


# ── Models ───────────────────────────────────────────────────────


class IntegrationFieldResponse(BaseModel):
    name: str
    label: str
    type: str
    required: bool
    help_text: str
    placeholder: str


class IntegrationStatusResponse(BaseModel):
    configured: bool
    missing_fields: list[str]


class IntegrationResponse(BaseModel):
    name: str
    display_name: str
    description: str
    fields: list[IntegrationFieldResponse]
    status: IntegrationStatusResponse
    config: dict  # current config values (secrets masked)


class IntegrationsListResponse(BaseModel):
    integrations: list[IntegrationResponse]


class IntegrationConfigUpdate(BaseModel):
    config: dict


# ── Helpers ──────────────────────────────────────────────────────


def _mask_value(field_type: str, value: str) -> str:
    """Mask secret values for display."""
    if field_type == "secret" and value:
        if len(value) <= 8:
            return "••••••••"
        return value[:4] + "••••" + value[-4:]
    return value


def _build_response(integration, cogent_name: str, secrets_provider) -> dict:
    config = integration.load_config(cogent_name, secrets_provider=secrets_provider)
    status = integration.status(cogent_name, secrets_provider=secrets_provider, _config=config)

    # Mask secret fields
    field_types = {f.name: f.field_type for f in integration.fields()}
    masked_config = {}
    for k, v in config.items():
        if k == "type":
            continue
        ft = field_types.get(k, "text")
        masked_config[k] = _mask_value(ft, str(v)) if v else ""

    return {
        **integration.to_dict(),
        "status": status,
        "config": masked_config,
    }


# ── Routes ───────────────────────────────────────────────────────


@router.get("/integrations", response_model=IntegrationsListResponse)
async def list_integrations(name: str):
    """List all available integrations and their current status."""
    sp = _get_secrets_provider()
    items = [_build_response(i, name, sp) for i in INTEGRATIONS]
    return {"integrations": items}


@router.get("/integrations/{integration_name}")
async def get_integration(name: str, integration_name: str):
    """Get a single integration's definition and status."""
    integration = INTEGRATIONS_BY_NAME.get(integration_name)
    if not integration:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {integration_name}")
    sp = _get_secrets_provider()
    return _build_response(integration, name, sp)


@router.put("/integrations/{integration_name}")
async def update_integration(name: str, integration_name: str, body: IntegrationConfigUpdate):
    """Update an integration's configuration."""
    integration = INTEGRATIONS_BY_NAME.get(integration_name)
    if not integration:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {integration_name}")
    sp = _get_secrets_provider()
    integration.save_config(name, body.config, secrets_provider=sp)
    return _build_response(integration, name, sp)


@router.get("/integrations/{integration_name}/reveal/{field_name}")
async def reveal_field(name: str, integration_name: str, field_name: str):
    """Return the unmasked value of a single secret field."""
    integration = INTEGRATIONS_BY_NAME.get(integration_name)
    if not integration:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {integration_name}")
    field_types = {f.name: f.field_type for f in integration.fields()}
    if field_name not in field_types:
        raise HTTPException(status_code=404, detail=f"Unknown field: {field_name}")
    if field_types[field_name] != "secret":
        raise HTTPException(status_code=400, detail="Only secret fields can be revealed")
    sp = _get_secrets_provider()
    config = integration.load_config(name, secrets_provider=sp)
    value = config.get(field_name, "")
    return {"value": value}


@router.delete("/integrations/{integration_name}")
async def delete_integration(name: str, integration_name: str):
    """Remove an integration's stored configuration."""
    integration = INTEGRATIONS_BY_NAME.get(integration_name)
    if not integration:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {integration_name}")
    sp = _get_secrets_provider()
    integration.delete_config(name, secrets_provider=sp)
    return {"ok": True}
