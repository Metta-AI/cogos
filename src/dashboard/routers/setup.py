from __future__ import annotations

import logging
import os
from enum import Enum

from fastapi import APIRouter
from pydantic import BaseModel

import json

import boto3
from botocore.exceptions import ClientError

from cogos.io.discord.setup import discord_secret_status, discord_service_status
from dashboard.db import get_repo

logger = logging.getLogger(__name__)

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
    safe_name = name.replace(".", "-")
    secret_path = f"cogent/{name}/discord"
    service_name = f"cogent-{safe_name}-discord"
    create_bot_instructions = (
        "In Discord Developer Portal:\n"
        "1. Open the app and go to Bot.\n"
        "2. If needed, click Add Bot or Reset Token so you have a bot user and token.\n"
        "3. Enable Message Content Intent.\n"
        "4. Go to Installation and enable Guild Install.\n"
        "5. Add scopes: bot and applications.commands.\n"
        "6. Choose permissions and use the generated install link to invite the bot to your test server.\n"
        "If your server is missing from the picker, your Discord account cannot install apps there."
    )
    create_bot_if_missing = (
        "If the bot is not in your server yet, use these steps:\n"
        f"{create_bot_instructions}"
    )

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
        # Check for channel-based handlers for discord
        dm_handler_enabled = False
        mention_handler_enabled = False
        for h in handlers:
            if not h.enabled:
                continue
            ch_name = None
            if h.channel:
                ch = repo.get_channel(h.channel)
                ch_name = ch.name if ch else None
            if ch_name in ("io:discord:dm", "discord:dm"):
                dm_handler_enabled = True
            elif ch_name in ("io:discord:mention", "discord:mention"):
                mention_handler_enabled = True
    except Exception as exc:
        logger.warning("CogOS setup check failed for %s: %s", name, exc)
        cogos_initialized = False
        cogos_error = type(exc).__name__

    secret_configured, secret_check_error = discord_secret_status(name, region)
    service_status, service_check_error = discord_service_status(name, region)
    bridge_running = (
        service_status["bridge_running_count"] is not None
        and int(service_status["bridge_running_count"]) > 0
    )
    wiring_ready = (
        cogos_initialized
        and capability_enabled
        and dm_handler_enabled
        and mention_handler_enabled
    )
    ready_for_test = wiring_ready and secret_configured is True and bridge_running

    diagnostics: list[str] = []
    if cogos_error:
        diagnostics.append(f"CogOS checks unavailable: {cogos_error}")
    if secret_check_error:
        diagnostics.append(f"Discord secret check unavailable: {secret_check_error}")
    if service_check_error:
        diagnostics.append(f"Discord service check unavailable: {service_check_error}")

    if wiring_ready:
        cogos_step = SetupStep(
            key="cogos-defaults",
            title="Load CogOS defaults",
            description="Fresh cogtainer bring-up needs the default CogOS image so the Discord capability and handlers exist.",
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
            description="Fresh cogtainer bring-up needs the default CogOS image so the Discord capability and handlers exist.",
            status=SetupStatus.NEEDS_ACTION,
            detail=detail,
            action=SetupAction(
                label="Reload CogOS defaults",
                command=f"uv run cogent {name} cogos reload --yes",
            ),
        )

    if secret_configured is True:
        create_bot_step = SetupStep(
            key="create-bot",
            title="Create and invite the bot",
            description="Create the Discord app, confirm the bot user exists, turn on Message Content Intent, and invite it to the server where you want to test.",
            status=SetupStatus.READY,
            detail=(
                "A Discord token is already stored, so the bot was probably created.\n"
                f"{create_bot_if_missing}"
            ),
            action=SetupAction(
                label="Open Discord Developer Portal",
                href="https://discord.com/developers/applications",
            ),
        )
    elif secret_configured is False:
        create_bot_step = SetupStep(
            key="create-bot",
            title="Create and invite the bot",
            description="Create the Discord app, confirm the bot user exists, turn on Message Content Intent, and invite it to the server where you want to test.",
            status=SetupStatus.NEEDS_ACTION,
            detail=(
                "This dashboard cannot verify Discord-side configuration, and there is no token stored yet.\n"
                f"{create_bot_instructions}"
            ),
            action=SetupAction(
                label="Open Discord Developer Portal",
                href="https://discord.com/developers/applications",
            ),
        )
    else:
        create_bot_step = SetupStep(
            key="create-bot",
            title="Create and invite the bot",
            description="Create the Discord app, confirm the bot user exists, turn on Message Content Intent, and invite it to the server where you want to test.",
            status=SetupStatus.UNKNOWN,
            detail=(
                "Live token checks are unavailable, so this step cannot be confirmed from the dashboard.\n"
                f"{create_bot_if_missing}"
            ),
            action=SetupAction(
                label="Open Discord Developer Portal",
                href="https://discord.com/developers/applications",
            ),
        )

    if secret_configured is True:
        secret_step = SetupStep(
            key="store-token",
            title="Store the bot token",
            description="The Discord bridge reads the bot token from Secrets Manager.",
            status=SetupStatus.READY,
            detail=f"Token is present at {secret_path}.",
        )
    elif secret_configured is False:
        secret_step = SetupStep(
            key="store-token",
            title="Store the bot token",
            description="Write the bot token into polis secrets so the bridge can log in.",
            status=SetupStatus.NEEDS_ACTION,
            detail=f"Expected secret path: {secret_path}.",
            action=SetupAction(
                label="Write Discord token",
                command=f"""uv run polis secrets set {secret_path} --value '{{"access_token":"YOUR_BOT_TOKEN"}}'""",
            ),
        )
    else:
        secret_step = SetupStep(
            key="store-token",
            title="Store the bot token",
            description="Write the bot token into polis secrets so the bridge can log in.",
            status=SetupStatus.UNKNOWN,
            detail=f"Expected secret path: {secret_path}. Latest check error: {secret_check_error}.",
            action=SetupAction(
                label="Write Discord token",
                command=f"""uv run polis secrets set {secret_path} --value '{{"access_token":"YOUR_BOT_TOKEN"}}'""",
            ),
        )

    if bridge_running:
        bridge_step = SetupStep(
            key="start-bridge",
            title="Start the Discord bridge",
            description="The Discord bridge runs as its own ECS service.",
            status=SetupStatus.READY,
            detail=f"{service_name} is running.",
        )
    elif service_status["bridge_service_exists"] is False:
        bridge_step = SetupStep(
            key="start-bridge",
            title="Start the Discord bridge",
            description="The Discord bridge runs as its own ECS service.",
            status=SetupStatus.NEEDS_ACTION,
            detail=f"{service_name} does not exist yet.",
            action=SetupAction(
                label="Deploy cogtainer stack",
                command=f"uv run cogent {name} cogtainer update stack",
            ),
        )
    elif service_status["bridge_service_exists"] is True:
        bridge_step = SetupStep(
            key="start-bridge",
            title="Start the Discord bridge",
            description="The Discord bridge runs as its own ECS service.",
            status=SetupStatus.NEEDS_ACTION,
            detail=f"{service_name} exists but is not running.",
            action=SetupAction(
                label="Start Discord bridge",
                command=f"uv run cogent {name} cogos discord start",
            ),
        )
    else:
        bridge_step = SetupStep(
            key="start-bridge",
            title="Start the Discord bridge",
            description="The Discord bridge runs as its own ECS service.",
            status=SetupStatus.UNKNOWN,
            detail=f"Service status checks are unavailable. Expected service name: {service_name}.",
            action=SetupAction(
                label="Check bridge status",
                command=f"uv run cogent {name} cogos discord status",
            ),
        )

    if ready_for_test:
        test_step = SetupStep(
            key="send-test-message",
            title="Send a test message",
            description="Once the bridge is live, DM the bot directly or @mention it in a server channel.",
            status=SetupStatus.MANUAL,
            detail="Plain channel chatter will not trigger it.",
        )
    else:
        test_step = SetupStep(
            key="send-test-message",
            title="Send a test message",
            description="Once the bridge is live, DM the bot directly or @mention it in a server channel.",
            status=SetupStatus.NEEDS_ACTION,
            detail="Finish the earlier steps first. Plain channel chatter will not trigger it.",
        )

    status = (
        SetupStatus.READY
        if ready_for_test
        else SetupStatus.UNKNOWN
        if any(step.status == SetupStatus.UNKNOWN for step in (create_bot_step, secret_step, bridge_step))
        else SetupStatus.NEEDS_ACTION
    )
    summary = (
        "Discord is ready for end-to-end testing."
        if ready_for_test
        else "Some live checks were unavailable, but the setup steps below still apply."
        if status == SetupStatus.UNKNOWN
        else "Finish the remaining Discord setup steps, then DM the bot or @mention it."
    )

    return ChannelSetup(
        key="discord",
        title="Discord",
        description="Configure the Discord bridge, token, and default inbound wiring for this cogent.",
        status=status,
        summary=summary,
        ready_for_test=ready_for_test,
        steps=[
            cogos_step,
            create_bot_step,
            secret_step,
            bridge_step,
            test_step,
        ],
        diagnostics=diagnostics,
    )


def _gemini_secret_status(
    name: str,
    region: str,
) -> tuple[bool | None, str | None]:
    secret_id = f"cogent/{name}/gemini"
    sm = boto3.client("secretsmanager", region_name=region)
    try:
        resp = sm.get_secret_value(SecretId=secret_id)
        data = json.loads(resp.get("SecretString", "{}"))
        return bool(data.get("api_key")), None
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ResourceNotFoundException":
            return False, None
        logger.warning("Gemini secret check failed for %s: %s", name, code or exc)
        return None, code or type(exc).__name__
    except Exception as exc:
        logger.warning("Gemini secret check failed for %s: %s", name, exc)
        return None, type(exc).__name__


def _build_gemini_setup(name: str) -> ChannelSetup:
    region = os.environ.get("AWS_REGION", "us-east-1")
    secret_path = f"cogent/{name}/gemini"

    secret_configured, secret_check_error = _gemini_secret_status(name, region)

    diagnostics: list[str] = []
    if secret_check_error:
        diagnostics.append(f"Gemini secret check unavailable: {secret_check_error}")

    if secret_configured is True:
        get_key_step = SetupStep(
            key="get-api-key",
            title="Get a Gemini API key",
            description="Create an API key in Google AI Studio for image generation.",
            status=SetupStatus.READY,
            detail="A Gemini API key is already stored.",
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
            detail=f"Key is present at {secret_path}.",
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
            description="Write the API key into polis secrets so the image capability can use it.",
            status=SetupStatus.NEEDS_ACTION,
            detail=f"Expected secret path: {secret_path}.",
            action=SetupAction(
                label="Write Gemini API key",
                command=f"""uv run polis secrets set {secret_path} --value '{{"api_key":"YOUR_GEMINI_API_KEY"}}'""",
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
            description="Write the API key into polis secrets so the image capability can use it.",
            status=SetupStatus.UNKNOWN,
            detail=f"Expected secret path: {secret_path}. Latest check error: {secret_check_error}.",
            action=SetupAction(
                label="Write Gemini API key",
                command=f"""uv run polis secrets set {secret_path} --value '{{"api_key":"YOUR_GEMINI_API_KEY"}}'""",
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
    summary = (
        "Gemini API key is configured and ready for image generation."
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


@router.get("/setup", response_model=SetupResponse)
def get_setup(name: str) -> SetupResponse:
    return SetupResponse(channels=[
        _build_discord_setup(name),
        _build_gemini_setup(name),
    ])
