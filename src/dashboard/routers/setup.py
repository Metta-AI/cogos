from __future__ import annotations

import json
import logging
import os
from enum import Enum

from fastapi import APIRouter
from pydantic import BaseModel

from cogos.io.discord.setup import discord_persona_status, discord_secret_status, discord_service_status
from cogtainer.secrets import AwsSecretsProvider
from dashboard.db import get_repo

logger = logging.getLogger(__name__)

_region = os.environ.get("AWS_REGION", "us-east-1")

_secrets_provider = None


def _get_secrets_provider():
    global _secrets_provider
    if _secrets_provider is None:
        _secrets_provider = AwsSecretsProvider(region=_region)
    return _secrets_provider


def _get_ecs_client():
    """Return an ECS client, or None if unavailable."""
    try:
        import boto3
        return boto3.client("ecs", region_name=_region)
    except Exception:
        return None

router = APIRouter(tags=["setup"])


class SetupStatus(str, Enum):
    READY = "ready"
    NEEDS_ACTION = "needs_action"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class SetupAction(BaseModel):
    label: str
    command: str | None = None
    href: str | None = None


class SetupStep(BaseModel):
    key: str
    title: str
    description: str
    status: SetupStatus
    detail: str | None = None
    action: SetupAction | None = None


class ChannelSetup(BaseModel):
    key: str
    title: str
    description: str
    status: SetupStatus
    summary: str
    ready_for_test: bool
    steps: list[SetupStep]
    diagnostics: list[str] = []


class SetupResponse(BaseModel):
    channels: list[ChannelSetup]

def _build_discord_setup(name: str) -> ChannelSetup:
    region = os.environ.get("AWS_REGION", "us-east-1")

    cogos_initialized = True
    cogos_error = None
    capability_enabled = False
    dm_handler_enabled = False
    mention_handler_enabled = False

    try:
        repo = get_repo()
        caps = repo.list_capabilities()
        capability_enabled = any(cap.name == "discord" and cap.enabled for cap in caps)

        handlers = repo.list_handlers()
        for h in handlers:
            if not h.enabled:
                continue
            ch_name = None
            if h.channel:
                ch = repo.get_channel(h.channel)
                ch_name = ch.name if ch else None
            if ch_name and (":dm" in ch_name):
                dm_handler_enabled = True
            elif ch_name and (":mention" in ch_name):
                mention_handler_enabled = True
    except Exception as exc:
        logger.warning("CogOS setup check failed for %s: %s", name, exc)
        cogos_initialized = False
        cogos_error = type(exc).__name__

    # Shared bot token (cogtainer-level)
    secret_configured, secret_check_error = discord_secret_status(region, secrets_provider=_get_secrets_provider())
    # Shared bridge service (cogtainer-level)
    ecs_client = _get_ecs_client()
    if ecs_client is not None:
        service_status, service_check_error = discord_service_status(region, ecs_client=ecs_client)
        bridge_running = (
            service_status["bridge_running_count"] is not None
            and int(service_status["bridge_running_count"]) > 0
        )
    else:
        service_status = {}
        service_check_error = None
        bridge_running = False
    # Per-cogent persona config
    persona_data, persona_error = discord_persona_status(name, region, secrets_provider=_get_secrets_provider())
    has_persona = persona_data is not None and bool(persona_data.get("display_name"))

    wiring_ready = (
        cogos_initialized
        and capability_enabled
        and dm_handler_enabled
        and mention_handler_enabled
    )
    ready_for_test = wiring_ready and secret_configured is True and bridge_running and has_persona

    diagnostics: list[str] = []
    if cogos_error:
        diagnostics.append(f"CogOS checks unavailable: {cogos_error}")
    if secret_check_error:
        diagnostics.append(f"Discord secret check unavailable: {secret_check_error}")
    if service_check_error:
        diagnostics.append(f"Discord service check unavailable: {service_check_error}")
    if persona_error:
        diagnostics.append(f"Discord persona check unavailable: {persona_error}")

    if wiring_ready:
        cogos_step = SetupStep(
            key="cogos-defaults",
            title="Load CogOS defaults",
            description="The CogOS image provides the Discord capability and handlers.",
            status=SetupStatus.READY,
            detail="Discord capability, DM handler, and mention handler are loaded.",
        )
    else:
        detail = "Reload the default CogOS image to restore the Discord capability and handlers."
        if cogos_error:
            detail = f"{detail} Latest check error: {cogos_error}."
        cogos_step = SetupStep(
            key="cogos-defaults",
            title="Load CogOS defaults",
            description="The CogOS image provides the Discord capability and handlers.",
            status=SetupStatus.NEEDS_ACTION,
            detail=detail,
            action=SetupAction(
                label="Reload CogOS defaults",
                command=f"uv run cogent {name} cogos reload --yes",
            ),
        )

    # Persona config step
    if has_persona and persona_data is not None:
        persona_detail = f"Display name: {persona_data.get('display_name', name)}"
        if persona_data.get("default_channels"):
            persona_detail += f", default channels: {', '.join(persona_data['default_channels'])}"
        persona_step = SetupStep(
            key="persona-config",
            title="Configure Discord persona",
            description="Set display name, avatar, color, and default channels for this cogent.",
            status=SetupStatus.READY,
            detail=persona_detail,
        )
    else:
        persona_step = SetupStep(
            key="persona-config",
            title="Configure Discord persona",
            description="Set display name, avatar, color, and default channels for this cogent.",
            status=SetupStatus.NEEDS_ACTION,
            detail="No persona config found. The bridge uses this to create a mentionable role and webhook persona.",
            action=SetupAction(
                label="Set persona config",
                command=(
                    f"uv run cogtainer secrets set cogent/{name}/discord "
                    f"""--value '{{"display_name":"{name}","avatar_url":"","color":0,"default_channels":[]}}'"""
                ),
            ),
        )

    # Shared bridge status step
    if bridge_running:
        bridge_step = SetupStep(
            key="bridge-status",
            title="Shared Discord bridge",
            description="The shared Discord bridge runs as a cogtainer-level ECS service.",
            status=SetupStatus.READY,
            detail="cogtainer-discord is running.",
        )
    else:
        bridge_step = SetupStep(
            key="bridge-status",
            title="Shared Discord bridge",
            description="The shared Discord bridge runs as a cogtainer-level ECS service.",
            status=SetupStatus.NEEDS_ACTION,
            detail="cogtainer-discord is not running.",
            action=SetupAction(
                label="Deploy cogtainer stack",
                command="uv run cogtainer deploy",
            ),
        )

    if ready_for_test:
        test_step = SetupStep(
            key="send-test-message",
            title="Send a test message",
            description=f"Mention @cogent:{name} in a server channel or DM the bot.",
            status=SetupStatus.MANUAL,
            detail="The shared bridge routes messages by role mention.",
        )
    else:
        test_step = SetupStep(
            key="send-test-message",
            title="Send a test message",
            description=f"Mention @cogent:{name} in a server channel or DM the bot.",
            status=SetupStatus.NEEDS_ACTION,
            detail="Finish the earlier steps first.",
        )

    status = (
        SetupStatus.READY
        if ready_for_test
        else SetupStatus.UNKNOWN
        if any(step.status == SetupStatus.UNKNOWN for step in (persona_step, bridge_step))
        else SetupStatus.NEEDS_ACTION
    )
    summary = (
        "Discord is ready for end-to-end testing."
        if ready_for_test
        else "Finish the remaining Discord setup steps."
    )

    return ChannelSetup(
        key="discord",
        title="Discord",
        description="Configure this cogent's Discord persona. The shared bridge handles routing and delivery.",
        status=status,
        summary=summary,
        ready_for_test=ready_for_test,
        steps=[
            cogos_step,
            persona_step,
            bridge_step,
            test_step,
        ],
        diagnostics=diagnostics,
    )


def _gemini_secret_status(
    name: str,
    region: str,
) -> tuple[bool | None, str | None, str | None]:
    """Return (configured, error, source_path) for the Gemini secret."""
    from cogtainer.secrets import cogtainer_key
    sp = _get_secrets_provider()
    for secret_id in (f"cogent/{name}/gemini", cogtainer_key("gemini")):
        try:
            raw = sp.get_secret(secret_id)
            data = json.loads(raw)
            if data.get("api_key"):
                return True, None, secret_id
        except KeyError:
            continue
        except Exception as exc:
            logger.warning("Gemini secret check failed for %s: %s", name, exc)
            return None, type(exc).__name__, None
    return False, None, None


def _build_gemini_setup(name: str) -> ChannelSetup:
    region = os.environ.get("AWS_REGION", "us-east-1")
    secret_path = f"cogent/{name}/gemini"

    secret_configured, secret_check_error, secret_source = _gemini_secret_status(name, region)

    diagnostics: list[str] = []
    if secret_check_error:
        diagnostics.append(f"Gemini secret check unavailable: {secret_check_error}")

    if secret_configured is True:
        get_key_step = SetupStep(
            key="get-api-key",
            title="Get a Gemini API key",
            description="Create an API key in Google AI Studio for image generation.",
            status=SetupStatus.READY,
            detail=f"A Gemini API key is already stored (source: {secret_source}).",
            action=SetupAction(
                label="Open Google AI Studio",
                href="https://aistudio.google.com/apikey",
            ),
        )
        store_key_step = SetupStep(
            key="store-api-key",
            title="Store the API key",
            description="The image generation capability reads the Gemini key from Secrets Manager.",
            status=SetupStatus.READY,
            detail=f"Key is present at {secret_source}.",
        )
    elif secret_configured is False:
        get_key_step = SetupStep(
            key="get-api-key",
            title="Get a Gemini API key",
            description="Create an API key in Google AI Studio for image generation.",
            status=SetupStatus.NEEDS_ACTION,
            detail=(
                "Go to Google AI Studio, create a new API key, and copy it.\n"
                "The key is used for image generation (gemini-2.5-flash-image model)."
            ),
            action=SetupAction(
                label="Open Google AI Studio",
                href="https://aistudio.google.com/apikey",
            ),
        )
        store_key_step = SetupStep(
            key="store-api-key",
            title="Store the API key",
            description="Write the API key into cogtainer secrets so the image capability can use it.",
            status=SetupStatus.NEEDS_ACTION,
            detail=f"Expected secret path: {secret_path}.",
            action=SetupAction(
                label="Write Gemini API key",
                command=f"""uv run cogtainer secrets set {secret_path} --value '{{"api_key":"YOUR_GEMINI_API_KEY"}}'""",
            ),
        )
    else:
        get_key_step = SetupStep(
            key="get-api-key",
            title="Get a Gemini API key",
            description="Create an API key in Google AI Studio for image generation.",
            status=SetupStatus.UNKNOWN,
            detail="Live secret checks are unavailable.",
            action=SetupAction(
                label="Open Google AI Studio",
                href="https://aistudio.google.com/apikey",
            ),
        )
        store_key_step = SetupStep(
            key="store-api-key",
            title="Store the API key",
            description="Write the API key into cogtainer secrets so the image capability can use it.",
            status=SetupStatus.UNKNOWN,
            detail=f"Expected secret path: {secret_path}. Latest check error: {secret_check_error}.",
            action=SetupAction(
                label="Write Gemini API key",
                command=f"""uv run cogtainer secrets set {secret_path} --value '{{"api_key":"YOUR_GEMINI_API_KEY"}}'""",
            ),
        )

    test_step = SetupStep(
        key="test-generation",
        title="Test image generation",
        description="Ask the cogent to generate an image via Discord or another channel to confirm it works.",
        status=SetupStatus.MANUAL if secret_configured is True else SetupStatus.NEEDS_ACTION,
        detail=(
            "Try asking the cogent to generate an image."
            if secret_configured is True
            else "Finish the earlier steps first."
        ),
    )

    ready = secret_configured is True
    status = (
        SetupStatus.READY
        if ready
        else SetupStatus.UNKNOWN
        if any(s.status == SetupStatus.UNKNOWN for s in (get_key_step, store_key_step))
        else SetupStatus.NEEDS_ACTION
    )
    is_shared = secret_source is not None and secret_source.startswith("cogtainer/") if secret_source else False
    summary = (
        f"Gemini API key is configured via {'shared' if is_shared else 'cogent-specific'}"
        " secret and ready for image generation."
        if ready
        else "Some live checks were unavailable."
        if status == SetupStatus.UNKNOWN
        else "Store a Gemini API key to enable image generation."
    )

    return ChannelSetup(
        key="gemini",
        title="Image Generation",
        description="Configure the Gemini API key for AI image generation (used by the image capability).",
        status=status,
        summary=summary,
        ready_for_test=ready,
        steps=[get_key_step, store_key_step, test_step],
        diagnostics=diagnostics,
    )


def _asana_secret_status(
    name: str,
    region: str,
) -> tuple[bool | None, str | None]:
    from cogos.io.integration import INTEGRATIONS_BY_NAME

    integration = INTEGRATIONS_BY_NAME["asana"]
    try:
        status = integration.status(name, secrets_provider=_get_secrets_provider())
        return status["configured"], None
    except Exception as exc:
        logger.warning("Asana secret check failed for %s: %s", name, exc)
        return None, type(exc).__name__


def _build_asana_setup(name: str) -> ChannelSetup:
    region = os.environ.get("AWS_REGION", "us-east-1")
    secret_path = f"cogent/{name}/asana"

    secret_configured, secret_check_error = _asana_secret_status(name, region)

    diagnostics: list[str] = []
    if secret_check_error:
        diagnostics.append(f"Asana secret check unavailable: {secret_check_error}")

    if secret_configured is True:
        get_token_step = SetupStep(
            key="get-access-token",
            title="Get an Asana Personal Access Token",
            description="Create a Personal Access Token in Asana Developer Console.",
            status=SetupStatus.READY,
            detail="An Asana access token is already stored.",
            action=SetupAction(
                label="Open Asana Developer Console",
                href="https://app.asana.com/0/developer-console",
            ),
        )
        store_token_step = SetupStep(
            key="store-access-token",
            title="Store the access token",
            description="The Asana capability reads the token from Secrets Manager.",
            status=SetupStatus.READY,
            detail=f"Token is present at {secret_path}.",
        )
    elif secret_configured is False:
        get_token_step = SetupStep(
            key="get-access-token",
            title="Get an Asana Personal Access Token",
            description="Create a Personal Access Token in Asana Developer Console.",
            status=SetupStatus.NEEDS_ACTION,
            detail=(
                "Go to Asana Developer Console, click 'Create new token', "
                "give it a name, and copy the token value.\n"
                "The token is used by both the Asana capability (task management) "
                "and the Asana IO adapter (polling for assignments)."
            ),
            action=SetupAction(
                label="Open Asana Developer Console",
                href="https://app.asana.com/0/developer-console",
            ),
        )
        store_token_step = SetupStep(
            key="store-access-token",
            title="Store the access token",
            description="Write the access token into cogtainer secrets so the Asana capability can use it.",
            status=SetupStatus.NEEDS_ACTION,
            detail=f"Expected secret path: {secret_path}.",
            action=SetupAction(
                label="Write Asana access token",
                command=f"""uv run cogtainer secrets set {secret_path} --value '{{"access_token":"YOUR_ASANA_PAT"}}'""",
            ),
        )
    else:
        get_token_step = SetupStep(
            key="get-access-token",
            title="Get an Asana Personal Access Token",
            description="Create a Personal Access Token in Asana Developer Console.",
            status=SetupStatus.UNKNOWN,
            detail="Live secret checks are unavailable.",
            action=SetupAction(
                label="Open Asana Developer Console",
                href="https://app.asana.com/0/developer-console",
            ),
        )
        store_token_step = SetupStep(
            key="store-access-token",
            title="Store the access token",
            description="Write the access token into cogtainer secrets so the Asana capability can use it.",
            status=SetupStatus.UNKNOWN,
            detail=f"Expected secret path: {secret_path}. Latest check error: {secret_check_error}.",
            action=SetupAction(
                label="Write Asana access token",
                command=f"""uv run cogtainer secrets set {secret_path} --value '{{"access_token":"YOUR_ASANA_PAT"}}'""",
            ),
        )

    test_step = SetupStep(
        key="test-asana",
        title="Test the integration",
        description="Use the Asana capability to list tasks or create a test task in a project.",
        status=SetupStatus.MANUAL if secret_configured is True else SetupStatus.NEEDS_ACTION,
        detail=(
            "Try asking the cogent to list Asana tasks in a project."
            if secret_configured is True
            else "Finish the earlier steps first."
        ),
    )

    ready = secret_configured is True
    status = (
        SetupStatus.READY
        if ready
        else SetupStatus.UNKNOWN
        if any(s.status == SetupStatus.UNKNOWN for s in (get_token_step, store_token_step))
        else SetupStatus.NEEDS_ACTION
    )
    summary = (
        "Asana access token is configured and ready."
        if ready
        else "Some live checks were unavailable."
        if status == SetupStatus.UNKNOWN
        else "Store an Asana Personal Access Token to enable task management."
    )

    return ChannelSetup(
        key="asana",
        title="Asana",
        description="Configure the Asana Personal Access Token for task management and assignment polling.",
        status=status,
        summary=summary,
        ready_for_test=ready,
        steps=[get_token_step, store_token_step, test_step],
        diagnostics=diagnostics,
    )


def _build_profile_setup(name: str) -> ChannelSetup:
    region = os.environ.get("AWS_REGION", "us-east-1")

    cogent_name = _read_secret_value(f"cogent/{name}/identity/name", region)
    has_name = bool(cogent_name)

    detail_lines = [
        f"- **Cogent Name:** {cogent_name or '(not set)'}",
    ]

    if has_name:
        edit_step = SetupStep(
            key="edit-profile",
            title="Edit cogent profile",
            description="Update the cogent's name.",
            status=SetupStatus.READY,
            detail="\n".join(detail_lines),
        )
    else:
        edit_step = SetupStep(
            key="edit-profile",
            title="Edit cogent profile",
            description="Set the cogent's name in Secrets Manager.",
            status=SetupStatus.NEEDS_ACTION,
            detail="\n".join(detail_lines),
        )

    status = SetupStatus.READY if has_name else SetupStatus.NEEDS_ACTION
    summary = (
        "Cogent identity is configured."
        if has_name
        else "Set the cogent's name in Secrets Manager."
    )

    return ChannelSetup(
        key="profile",
        title="Profile",
        description="Configure the cogent's identity.",
        status=status,
        summary=summary,
        ready_for_test=has_name,
        steps=[edit_step],
    )


def _anthropic_secret_status(
    name: str,
    region: str,
) -> tuple[bool | None, str | None]:
    from cogos.io.integration import INTEGRATIONS_BY_NAME

    integration = INTEGRATIONS_BY_NAME["anthropic"]
    try:
        status = integration.status(name, secrets_provider=_get_secrets_provider())
        return status["configured"], None
    except Exception as exc:
        logger.warning("Anthropic secret check failed for %s: %s", name, exc)
        return None, type(exc).__name__


def _build_anthropic_setup(name: str) -> ChannelSetup:
    secret_path = f"cogent/{name}/anthropic"
    secret_configured, secret_check_error = _anthropic_secret_status(name, os.environ.get("AWS_REGION", "us-east-1"))

    diagnostics: list[str] = []
    if secret_check_error:
        diagnostics.append(f"Anthropic secret check unavailable: {secret_check_error}")

    if secret_configured is True:
        key_step = SetupStep(
            key="store-api-key",
            title="Store the API key",
            description="The Anthropic API key is stored in Secrets Manager.",
            status=SetupStatus.READY,
            detail="An Anthropic API key is already stored.",
        )
    elif secret_configured is False:
        key_step = SetupStep(
            key="store-api-key",
            title="Store the API key",
            description="Write the API key into cogtainer secrets.",
            status=SetupStatus.NEEDS_ACTION,
            detail=f"Expected secret path: {secret_path}.",
            action=SetupAction(
                label="Write Anthropic API key",
                command=(
                    f"uv run cogtainer secrets set {secret_path}"
                    """ --value '{"api_key":"YOUR_ANTHROPIC_API_KEY"}'"""
                ),
            ),
        )
    else:
        key_step = SetupStep(
            key="store-api-key",
            title="Store the API key",
            description="Write the API key into cogtainer secrets.",
            status=SetupStatus.UNKNOWN,
            detail=f"Expected secret path: {secret_path}. Latest check error: {secret_check_error}.",
        )

    ready = secret_configured is True
    if ready:
        status = SetupStatus.READY
    elif key_step.status == SetupStatus.UNKNOWN:
        status = SetupStatus.UNKNOWN
    else:
        status = SetupStatus.NEEDS_ACTION
    summary = (
        "Anthropic API key is configured."
        if ready
        else "Store an Anthropic API key to enable Claude model access."
    )

    return ChannelSetup(
        key="anthropic",
        title="Anthropic",
        description="Configure the Anthropic API key for Claude model access.",
        status=status,
        summary=summary,
        ready_for_test=ready,
        steps=[key_step],
        diagnostics=diagnostics,
    )


def _email_ses_status(
    domain: str,
    region: str,
) -> tuple[bool | None, str | None]:
    """Check if the email domain is verified in SES."""
    if not domain:
        return False, None
    from cogtainer.io.email.provision import ses_domain_status

    return ses_domain_status(domain=domain, region=region)


def _build_email_setup(name: str) -> ChannelSetup:
    from cogos.io.integration import EmailIntegration

    region = os.environ.get("AWS_REGION", "us-east-1")
    cogtainer_name = os.environ.get("COGTAINER", "")
    sp = _get_secrets_provider()
    domain = ""
    if cogtainer_name:
        try:
            domain = sp.get_secret(f"cogtainer/{cogtainer_name}/email/domain")
        except Exception:
            pass
    address = EmailIntegration.address_for(name, domain)

    # Check CogOS wiring
    cogos_initialized = True
    capability_enabled = False
    cogos_error = None
    try:
        repo = get_repo()
        caps = repo.list_capabilities()
        capability_enabled = any(cap.name == "email" and cap.enabled for cap in caps)
    except Exception as exc:
        logger.warning("CogOS email check failed for %s: %s", name, exc)
        cogos_initialized = False
        cogos_error = type(exc).__name__

    # SES domain verification
    ses_verified, ses_error = _email_ses_status(domain, region)

    diagnostics: list[str] = []
    if cogos_error:
        diagnostics.append(f"CogOS checks unavailable: {cogos_error}")
    if ses_error:
        diagnostics.append(f"SES domain check unavailable: {ses_error}")

    # Step 1: Address (always ready — auto-derived)
    address_step = SetupStep(
        key="email-address",
        title="Email address",
        description="Each cogent gets an email address derived from its name.",
        status=SetupStatus.READY,
        detail=f"Address: **{address}**",
    )

    # Step 2: CogOS capability wiring
    wiring_ready = cogos_initialized and capability_enabled
    if wiring_ready:
        wiring_step = SetupStep(
            key="cogos-defaults",
            title="CogOS email capability",
            description="The CogOS image provides the email capability.",
            status=SetupStatus.READY,
            detail="Email capability is loaded and enabled.",
        )
    else:
        detail = "Reload the default CogOS image to restore the email capability."
        if cogos_error:
            detail = f"{detail} Latest check error: {cogos_error}."
        wiring_step = SetupStep(
            key="cogos-defaults",
            title="CogOS email capability",
            description="The CogOS image provides the email capability.",
            status=SetupStatus.NEEDS_ACTION,
            detail=detail,
            action=SetupAction(
                label="Reload CogOS defaults",
                command=f"uv run cogent {name} cogos reload --yes",
            ),
        )

    # Step 3: SES domain verification
    if ses_verified is True:
        ses_step = SetupStep(
            key="ses-domain",
            title="SES domain verification",
            description=f"The domain {domain} must be verified in SES.",
            status=SetupStatus.READY,
            detail=f"Domain {domain} is verified in SES.",
        )
    elif ses_verified is False:
        ses_step = SetupStep(
            key="ses-domain",
            title="SES domain verification",
            description=f"The domain {domain} must be verified in SES.",
            status=SetupStatus.NEEDS_ACTION,
            detail=f"Domain {domain} is not verified in SES.",
            action=SetupAction(
                label="Deploy cogtainer stack",
                command="uv run cogtainer deploy",
            ),
        )
    else:
        ses_step = SetupStep(
            key="ses-domain",
            title="SES domain verification",
            description=f"The domain {domain} must be verified in SES.",
            status=SetupStatus.UNKNOWN,
            detail=f"Could not check SES domain status. Error: {ses_error}.",
        )

    ready_for_test = wiring_ready and ses_verified is True

    if ready_for_test:
        test_step = SetupStep(
            key="test-email",
            title="Test email",
            description=f"Send a test email to {address} and verify it arrives.",
            status=SetupStatus.MANUAL,
            detail="Diagnostics will test send/receive automatically.",
        )
    else:
        test_step = SetupStep(
            key="test-email",
            title="Test email",
            description=f"Send a test email to {address} and verify it arrives.",
            status=SetupStatus.NEEDS_ACTION,
            detail="Finish the earlier steps first.",
        )

    status = (
        SetupStatus.READY
        if ready_for_test
        else SetupStatus.UNKNOWN
        if any(s.status == SetupStatus.UNKNOWN for s in (wiring_step, ses_step))
        else SetupStatus.NEEDS_ACTION
    )
    summary = (
        f"Email is ready at {address}."
        if ready_for_test
        else "Finish the remaining email setup steps."
    )

    return ChannelSetup(
        key="email",
        title="Email",
        description=f"Send and receive email as {address}.",
        status=status,
        summary=summary,
        ready_for_test=ready_for_test,
        steps=[address_step, wiring_step, ses_step, test_step],
        diagnostics=diagnostics,
    )


@router.get("/setup", response_model=SetupResponse)
def get_setup(name: str) -> SetupResponse:
    return SetupResponse(channels=[
        _build_profile_setup(name),
        _build_email_setup(name),
        _build_discord_setup(name),
        _build_anthropic_setup(name),
        _build_gemini_setup(name),
        _build_asana_setup(name),
    ])


# ── Identity secrets API ─────────────────────────────────────


class IdentitySecrets(BaseModel):
    cogent_name: str = ""


def _read_secret_value(secret_id: str, region: str) -> str:
    """Read a plain string secret. Returns empty string on failure."""
    try:
        raw = _get_secrets_provider().get_secret(secret_id)
        # Unwrap JSON-encoded strings (e.g. "\"dr.alpha\"" → "dr.alpha")
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, str):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return raw
    except Exception:
        return ""


def _write_secret_value(secret_id: str, value: str, region: str) -> None:
    """Write a plain string as a JSON-encoded secret."""
    encoded = json.dumps(value)
    _get_secrets_provider().set_secret(secret_id, encoded)


@router.get("/identity", response_model=IdentitySecrets)
def get_identity(name: str) -> IdentitySecrets:
    """Read identity secrets for a cogent."""
    region = os.environ.get("AWS_REGION", "us-east-1")
    return IdentitySecrets(
        cogent_name=_read_secret_value(f"cogent/{name}/identity/name", region),
    )


@router.put("/identity", response_model=IdentitySecrets)
def put_identity(name: str, body: IdentitySecrets) -> IdentitySecrets:
    """Write identity secrets for a cogent."""
    region = os.environ.get("AWS_REGION", "us-east-1")
    if body.cogent_name:
        _write_secret_value(f"cogent/{name}/identity/name", body.cogent_name, region)
    return get_identity(name)
