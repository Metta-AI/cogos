"""CLI for managing cogtainers (create, destroy, list, status)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click
import yaml

from cogtainer import naming
from cogtainer.config import (
    CogtainerEntry,
    CogtainersConfig,
    LLMConfig,
    global_config_path,
    load_config,
    local_config_path,
    local_data_dir,
)


def _config_path() -> Path:
    """Return the global config file path from env or default.

    Kept for callers that need the global path explicitly.
    """
    return global_config_path()


def _load() -> CogtainersConfig:
    """Load the merged cogtainers config (global + local)."""
    return load_config()


def _save_entry(name: str, entry: CogtainerEntry, cfg: CogtainersConfig) -> None:
    """Save an entry to the appropriate config file based on type."""
    if entry.type == "aws":
        _save_to_file(global_config_path(), name, entry, cfg)
    else:
        _save_to_file(local_config_path(), name, entry, cfg)


def _save_to_file(
    path: Path, name: str, entry: CogtainerEntry, merged_cfg: CogtainersConfig
) -> None:
    """Write entries belonging to this file, preserving others already in it."""
    from cogtainer.config import _load_yaml

    existing = _load_yaml(path)
    existing.cogtainers[name] = entry

    # For the local file, also save defaults
    is_local = path == local_config_path()
    if is_local:
        existing.defaults = merged_cfg.defaults

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(existing.model_dump(exclude_none=True), f, default_flow_style=False)


def _remove_from_file(path: Path, name: str) -> None:
    """Remove an entry from a config file."""
    from cogtainer.config import _load_yaml

    existing = _load_yaml(path)
    if name in existing.cogtainers:
        del existing.cogtainers[name]
        if existing.defaults.cogtainer == name:
            existing.defaults.cogtainer = None
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(existing.model_dump(exclude_none=True), f, default_flow_style=False)


def _pick(label: str, names: list[str]) -> str:
    """Present a numbered list and return the chosen name."""
    click.echo(f"Available {label}s:")
    for i, n in enumerate(names, 1):
        click.echo(f"  {i}) {n}")
    while True:
        raw = click.prompt(f"Select {label} (number or name)")
        if raw in names:
            return raw
        try:
            idx = int(raw)
            if 1 <= idx <= len(names):
                return names[idx - 1]
        except ValueError:
            pass
        click.echo(f"Invalid selection '{raw}'. Try again.")


DEFAULT_ORG_PROFILE = "softmax-org"
ORG_PROFILE_ENV = "COGENT_ORG_PROFILE"


def resolve_org_profile(profile: str | None = None) -> str:
    """Resolve the org-admin AWS profile."""
    for candidate in (profile, os.getenv(ORG_PROFILE_ENV)):
        if candidate and candidate.strip():
            return candidate.strip()
    return DEFAULT_ORG_PROFILE


def _cdk_create_account(cogtainer_name: str, region: str, profile: str | None = None) -> str:
    """Deploy the AccountStack via CDK and return the created account ID."""
    resolved_profile = resolve_org_profile(profile)
    stack_name = f"cogtainer-{cogtainer_name}-account"

    click.echo(f"  Deploying account stack '{stack_name}' via CDK...")
    cmd = [
        "npx", "cdk", "deploy", stack_name,
        "--app", "python -m cogtainer.cdk.app",
        "-c", f"cogtainer_name={cogtainer_name}",
        "-c", "stage=account",
        "-c", f"region={region}",
        "--require-approval", "never",
    ]
    env = {**os.environ, "AWS_PROFILE": resolved_profile}
    result = subprocess.run(cmd, capture_output=False, env=env)
    if result.returncode != 0:
        click.echo("CDK deploy failed.")
        sys.exit(result.returncode)

    # Read account ID from stack outputs
    import boto3
    session = boto3.Session(profile_name=resolved_profile, region_name=region)
    cfn = session.client("cloudformation")
    resp = cfn.describe_stacks(StackName=stack_name)
    outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}
    account_id = outputs.get("AccountId", "")
    if not account_id:
        raise RuntimeError(f"AccountId not found in {stack_name} outputs")
    click.echo(f"  Account ID: {account_id}")
    return account_id


@click.group()
def cli() -> None:
    """Manage cogtainers."""


@cli.command()
@click.argument("name")
@click.option("--type", "ctype", required=True, type=click.Choice(["aws", "local", "docker"]))
@click.option("--llm-provider", default="bedrock", help="LLM provider (bedrock, openrouter, anthropic)")
@click.option("--llm-model", default="us.anthropic.claude-sonnet-4-20250514-v1:0", help="Model name/ID")
@click.option("--llm-api-key-env", default="", help="Env var holding the API key (optional for bedrock)")
@click.option("--region", default=None)
@click.option("--domain", default=None)
@click.option("--profile", default=None, help="AWS profile name (for aws type)")
def create(
    name: str,
    ctype: str,
    llm_provider: str | None,
    llm_model: str | None,
    llm_api_key_env: str | None,
    region: str | None,
    domain: str | None,
    profile: str | None,
) -> None:
    """Create a new cogtainer."""
    cfg = _load()

    existing = cfg.cogtainers.get(name)
    if existing:
        # Allow re-running create to provision a missing AWS account
        if ctype == "aws" and existing.type == "aws" and not existing.account_id:
            click.echo(f"Cogtainer '{name}' exists without account_id, provisioning...")
            existing.account_id = _cdk_create_account(name, region=region or "us-east-1", profile=profile)
            _save_entry(name, existing, cfg)
            click.echo(f"Updated cogtainer '{name}' (account_id={existing.account_id}).")
            return
        click.echo(f"Cogtainer '{name}' already exists.")
        raise SystemExit(1)

    llm = LLMConfig(
        provider=llm_provider or "bedrock",
        model=llm_model if llm_model is not None else "",
        api_key_env=llm_api_key_env if llm_api_key_env is not None else "",
    )

    account_id = None

    if ctype == "aws":
        if not region:
            region = "us-east-1"
        account_id = _cdk_create_account(name, region=region, profile=profile)

    # Auto-assign unique dashboard ports for local/docker (base 8100/5200 + index)
    be_port = None
    fe_port = None
    if ctype in ("local", "docker"):
        idx = len(cfg.cogtainers)  # 0-based, before adding this one
        be_port = 8100 + idx
        fe_port = 5200 + idx

    entry = CogtainerEntry(
        type=ctype,
        region=region,
        account_id=account_id,
        domain=domain,
        llm=llm,
        dashboard_be_port=be_port,
        dashboard_fe_port=fe_port,
    )
    cfg.cogtainers[name] = entry

    # Set as default if it's the only local/docker cogtainer
    if ctype in ("local", "docker"):
        local_count = sum(1 for e in cfg.cogtainers.values() if e.type in ("local", "docker"))
        if local_count == 1:
            cfg.defaults.cogtainer = name
        # Ensure local data dir exists
        local_data_dir().mkdir(parents=True, exist_ok=True)

    _save_entry(name, entry, cfg)
    click.echo(f"Created cogtainer '{name}' (type={ctype}, account_id={account_id}).")

    # Prompt for cogtainer-level integration secrets
    _prompt_cogtainer_secrets(name, entry)


def _prompt_cogtainer_secrets(name: str, entry: CogtainerEntry) -> None:
    """Prompt for cogtainer-level integration secrets (enter to skip)."""
    from cogos.io.integration import INTEGRATIONS

    has_fields = [(i, i.cogtainer_fields()) for i in INTEGRATIONS if i.cogtainer_fields()]
    if not has_fields:
        return

    click.echo()
    click.echo("Configure integration secrets (press Enter to skip):")

    secrets: dict[str, str] = {}
    for integration, fields in has_fields:
        for field in fields:
            prompt = f"  {integration.display_name} — {field.label}"
            if field.help_text:
                prompt += f" ({field.help_text})"
            is_secret = field.field_type == "secret"
            value = click.prompt(prompt, default="", show_default=False, hide_input=is_secret)
            if value:
                key = f"cogtainer/{name}/{integration.name}/{field.name}"
                secrets[key] = value

    if not secrets:
        click.echo("  No secrets configured. You can set them later.")
        return

    # Write secrets
    region = entry.region or "us-east-1"
    try:
        from cogtainer.secrets import AwsSecretsProvider, LocalSecretsProvider

        if entry.type == "aws":
            sp = AwsSecretsProvider(region=region)
        else:
            sp = LocalSecretsProvider(data_dir=str(local_data_dir()))

        for key, value in secrets.items():
            sp.set_secret(key, value)
            click.echo(f"  Saved: {key}")
    except Exception as exc:
        click.echo(f"  Warning: could not save secrets ({exc}). Set them manually later.")


@cli.command()
@click.argument("name")
def destroy(name: str) -> None:
    """Destroy a cogtainer (remove from config)."""
    cfg = _load()

    if name not in cfg.cogtainers:
        click.echo(f"Cogtainer '{name}' not found.")
        raise SystemExit(1)

    if not click.confirm(f"Destroy cogtainer '{name}'?"):
        click.echo("Aborted.")
        return

    entry = cfg.cogtainers[name]
    del cfg.cogtainers[name]

    if cfg.defaults.cogtainer == name:
        cfg.defaults.cogtainer = None

    # Remove from the appropriate config file
    if entry.type == "aws":
        _remove_from_file(global_config_path(), name)
    else:
        _remove_from_file(local_config_path(), name)

    click.echo(f"Destroyed cogtainer '{name}'.")


@cli.command("list")
def list_cmd() -> None:
    """List all cogtainers."""
    cfg = _load()

    if not cfg.cogtainers:
        click.echo("No cogtainers configured.")
        return

    for name, entry in sorted(cfg.cogtainers.items()):
        default = " (default)" if cfg.defaults.cogtainer == name else ""
        provider = entry.llm.provider
        click.echo(f"  {name}  type={entry.type}  llm={provider}{default}")


@cli.command()
@click.argument("name", required=False)
def select(name: str | None) -> None:
    """Select a cogtainer by writing COGTAINER to .env."""
    cfg = _load()

    if not cfg.cogtainers:
        click.echo("No cogtainers configured.", err=True)
        raise SystemExit(1)

    if name is None:
        names = sorted(cfg.cogtainers)
        name = _pick("cogtainer", names)

    if name not in cfg.cogtainers:
        click.echo(f"Cogtainer '{name}' not found.", err=True)
        raise SystemExit(1)

    from cli.local_dev import write_repo_env

    env_path = write_repo_env({"COGTAINER": name})
    click.echo(f"Selected cogtainer '{name}' (wrote {env_path})")


@cli.command()
@click.argument("name", required=False)
def status(name: str | None) -> None:
    """Show details for a cogtainer."""
    cfg = _load()

    if name is None:
        from cogtainer.config import resolve_cogtainer_name

        name = resolve_cogtainer_name(cfg)

    if name not in cfg.cogtainers:
        click.echo(f"Cogtainer '{name}' not found.")
        raise SystemExit(1)

    entry = cfg.cogtainers[name]
    click.echo(f"Cogtainer: {name}")
    click.echo(f"  type: {entry.type}")
    if entry.region:
        click.echo(f"  region: {entry.region}")
    if entry.type in ("local", "docker"):
        click.echo(f"  data_dir: {local_data_dir()}")
        click.echo(f"  log_dir: {local_data_dir()}/{{cogent}}/logs")
    if entry.domain:
        click.echo(f"  domain: {entry.domain}")
    click.echo(f"  llm.provider: {entry.llm.provider}")
    click.echo(f"  llm.model: {entry.llm.model}")


@cli.command("compose")
@click.argument("name")
@click.option("--cogent", "cogent_names", multiple=True, help="Cogent names (repeatable)")
@click.option("--output", "output_path", default=None, help="Output path (default: data_dir/docker-compose.yml)")
def compose(name: str, cogent_names: tuple[str, ...], output_path: str | None) -> None:
    """Generate docker-compose.yml for a docker cogtainer."""
    cfg = _load()

    if name not in cfg.cogtainers:
        click.echo(f"Cogtainer '{name}' not found.")
        raise SystemExit(1)

    entry = cfg.cogtainers[name]
    if entry.type != "docker":
        click.echo(f"Cogtainer '{name}' is type '{entry.type}', not 'docker'.")
        raise SystemExit(1)

    if not cogent_names:
        click.echo("Specify at least one --cogent name.")
        raise SystemExit(1)

    from cogtainer.docker_compose import generate_compose

    content = generate_compose(entry, name, list(cogent_names))

    if output_path:
        out = Path(output_path)
    else:
        out = local_data_dir() / "docker-compose.yml"

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content)
    click.echo(f"Wrote {out}")


def _get_aws_session(
    region: str = "us-east-1",
    profile: str | None = None,
) -> tuple:
    """Get an AWS session for the cogtainer account. Separated for testability."""
    from cogtainer.aws import get_aws_session, set_org_profile

    if profile:
        set_org_profile(profile)
    else:
        set_org_profile()

    return get_aws_session()


@cli.command("discover-aws")
@click.option("--region", default="us-east-1", help="AWS region")
@click.option("--profile", default=None, help="AWS profile name")
def discover_aws(region: str, profile: str | None) -> None:
    """Discover existing AWS infrastructure and populate config."""
    session, account_id = _get_aws_session(region=region, profile=profile)

    # Scan DynamoDB cogent-status table
    ddb = session.resource("dynamodb", region_name=region)
    table = ddb.Table("cogent-status")

    items: list[dict] = []
    params: dict = {}
    while True:
        resp = table.scan(**params)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
        params["ExclusiveStartKey"] = last_key

    cogent_names = sorted(
        item["cogent_name"]
        for item in items
        if item.get("cogent_name")
    )

    if not cogent_names:
        click.echo("No cogents found in AWS.")
        return

    # Create or preserve cogtainer entry
    cfg = _load()
    if "aws" not in cfg.cogtainers:
        cfg.cogtainers["aws"] = CogtainerEntry(
            type="aws",
            region=region,
            account_id=account_id,
            llm=LLMConfig(
                provider="bedrock",
                model="us.anthropic.claude-sonnet-4-20250514-v1:0",
                api_key_env="",
            ),
        )
        _save_entry("aws", cfg.cogtainers["aws"], cfg)
        click.echo(f"Created cogtainer 'aws' (account={account_id}, region={region}).")
    else:
        click.echo("Cogtainer 'aws' already exists, keeping existing config.")

    click.echo(f"Discovered {len(cogent_names)} cogent(s):")
    for name in cogent_names:
        click.echo(f"  - {name}")


def _get_cogent_names(session, cogtainer_name: str, region: str) -> list[str]:
    """Get cogent names for a cogtainer.

    Tries DynamoDB status table first, falls back to discovering
    cogent names from Lambda function naming conventions.
    """
    # Try DynamoDB first
    try:
        ddb = session.resource("dynamodb", region_name=region)
        table_name = f"cogtainer-{cogtainer_name}-status"
        table = ddb.Table(table_name)
        items: list[dict] = []
        params: dict = {}
        while True:
            resp = table.scan(**params)
            items.extend(resp.get("Items", []))
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
            params["ExclusiveStartKey"] = last_key
        names = sorted(item["cogent_name"] for item in items if item.get("cogent_name"))
        if names:
            return names
    except Exception:
        pass

    # Also try legacy table name
    try:
        table = ddb.Table("cogent-status")
        items = []
        params = {}
        while True:
            resp = table.scan(**params)
            items.extend(resp.get("Items", []))
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
            params["ExclusiveStartKey"] = last_key
        names = sorted(item["cogent_name"] for item in items if item.get("cogent_name"))
        if names:
            return names
    except Exception:
        pass

    # Fall back: discover from Lambda function names
    lambda_client = session.client("lambda", region_name=region)
    prefix = f"cogtainer-{cogtainer_name}-"
    funcs = lambda_client.list_functions(MaxItems=200)["Functions"]
    cogent_names: set[str] = set()
    for f in funcs:
        fn = f["FunctionName"]
        if not fn.startswith(prefix):
            continue
        # Strip prefix and known suffixes to extract cogent name
        remainder = fn[len(prefix):]
        for suffix in ("-executor", "-dispatcher", "-event-router", "-ingress"):
            if remainder.endswith(suffix):
                name = remainder[: -len(suffix)]
                if name:
                    cogent_names.add(name.replace("-", "."))
                break
    return sorted(cogent_names)


def _update_lambdas(
    session,
    cogtainer_name: str,
    cogent_names: list[str],
    region: str,
    s3_bucket: str = "",
    s3_key: str = "",
    image_tag: str = "",
) -> None:
    """Update Lambda function code for all cogents."""
    lambda_client = session.client("lambda", region_name=region)
    suffixes = ["event-router", "executor", "dispatcher", "ingress"]

    for cogent_name in cogent_names:
        safe_name = cogent_name.replace(".", "-")
        for suffix in suffixes:
            fn_name = f"cogtainer-{cogtainer_name}-{safe_name}-{suffix}"
            try:
                kwargs: dict = {"FunctionName": fn_name}
                if s3_bucket and s3_key:
                    kwargs["S3Bucket"] = s3_bucket
                    kwargs["S3Key"] = s3_key
                elif image_tag:
                    # Get function config to find the image URI base
                    func_cfg = lambda_client.get_function_configuration(
                        FunctionName=fn_name,
                    )
                    current_image = func_cfg.get("Code", {}).get("ImageUri", "")
                    if current_image:
                        repo = current_image.rsplit(":", 1)[0]
                        kwargs["ImageUri"] = f"{repo}:{image_tag}"
                    else:
                        click.echo(f"  {fn_name}: no image URI, skipping --image-tag")
                        continue
                else:
                    click.echo(f"  {fn_name}: no update source specified, skipping")
                    continue

                lambda_client.update_function_code(**kwargs)
                click.echo(f"  {fn_name}: updated")
            except lambda_client.exceptions.ResourceNotFoundException:
                click.echo(f"  {fn_name}: not found (skip)")
            except Exception as e:
                click.echo(f"  {fn_name}: {e}")


def _update_services(
    session,
    cogtainer_name: str,
    cogent_names: list[str],
    region: str,
    image_tag: str = "",
) -> None:
    """Force new ECS deployment for all cogent services."""
    ecs_client = session.client("ecs", region_name=region)

    # Try cogtainer-prefixed cluster first, fall back to shared "cogtainer"
    cluster = f"cogtainer-{cogtainer_name}"
    try:
        resp = ecs_client.describe_clusters(clusters=[cluster])
        active = [c for c in resp.get("clusters", []) if c.get("status") == "ACTIVE"]
        if not active:
            cluster = naming.cluster_name()
    except Exception:
        cluster = naming.cluster_name()

    # List all services in the cluster and match by cogent name
    all_services: list[str] = []
    paginator = ecs_client.get_paginator("list_services")
    for page in paginator.paginate(cluster=cluster):
        for arn in page.get("serviceArns", []):
            all_services.append(arn.split("/")[-1])

    for cogent_name in cogent_names:
        safe_name = cogent_name.replace(".", "-")
        # Match services containing this cogent's safe name
        matching = [s for s in all_services if f"-{safe_name}-" in s]
        if not matching:
            click.echo(f"  {safe_name}: no services found (skip)")
            continue
        for service_name in matching:
            try:
                update_kwargs: dict = {
                    "cluster": cluster,
                    "service": service_name,
                    "forceNewDeployment": True,
                }
                if image_tag:
                    # Update the task definition with the new image
                    svc_resp = ecs_client.describe_services(cluster=cluster, services=[service_name])
                    td_arn = svc_resp["services"][0]["taskDefinition"]
                    td = ecs_client.describe_task_definition(taskDefinition=td_arn)["taskDefinition"]
                    new_containers = []
                    for c in td["containerDefinitions"]:
                        current_image = c.get("image", "")
                        if current_image:
                            repo = current_image.rsplit(":", 1)[0]
                            c = {**c, "image": f"{repo}:{image_tag}"}
                        new_containers.append(c)
                    # Register new task definition revision
                    reg_kwargs = {
                        k: td[k] for k in td
                        if k in (
                            "family", "taskRoleArn", "executionRoleArn", "networkMode",
                            "volumes", "placementConstraints", "requiresCompatibilities",
                            "cpu", "memory", "runtimePlatform",
                        ) and td.get(k)
                    }
                    reg_kwargs["containerDefinitions"] = new_containers
                    new_td = ecs_client.register_task_definition(**reg_kwargs)
                    new_td_arn = new_td["taskDefinition"]["taskDefinitionArn"]
                    update_kwargs["taskDefinition"] = new_td_arn
                ecs_client.update_service(**update_kwargs)
                click.echo(f"  {service_name}: restarted" + (f" (image: {image_tag})" if image_tag else ""))
            except Exception as e:
                click.echo(f"  {service_name}: {e}")


def _build_lambda_zip() -> bytes:
    """Package src/ with pip dependencies into a Lambda-ready zip."""
    import subprocess
    import tempfile
    import zipfile
    from io import BytesIO
    from pathlib import Path

    src_dir = Path(__file__).resolve().parent.parent  # repo/src

    # Install deps to a temp directory
    deps_dir = tempfile.mkdtemp()
    repo_root = src_dir.parent  # repo root
    req_file = repo_root / "sandbox-requirements.txt"
    install_cmd = [
        "uv", "pip", "install", "--target", deps_dir,
        "--quiet", "--python", "3.12", "--python-platform", "linux",
    ]
    if req_file.is_file():
        install_cmd += ["-r", str(req_file)]
    else:
        install_cmd += [
            "pydantic", "pydantic-settings", "pydantic-core", "annotated-types",
            "Pillow", "google-genai", "anthropic", "asana", "pyyaml",
        ]
    subprocess.run(install_cmd, check=True, capture_output=True)

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add src/
        for path in sorted(src_dir.rglob("*")):
            if path.is_dir():
                continue
            if "__pycache__" in str(path) or path.suffix == ".pyc":
                continue
            arcname = str(path.relative_to(src_dir))
            zf.write(path, arcname)

        # Add deps
        deps_path = Path(deps_dir)
        for path in sorted(deps_path.rglob("*")):
            if path.is_dir():
                continue
            if "__pycache__" in str(path) or path.suffix == ".pyc":
                continue
            arcname = str(path.relative_to(deps_path))
            zf.write(path, arcname)

    return buf.getvalue()


@cli.command("update")
@click.argument("name")
@click.option("--lambdas", "update_lambdas", is_flag=True, help="Update Lambda function code")
@click.option("--services", "update_services", is_flag=True, help="Restart ECS services with new image")
@click.option("--all", "update_all", is_flag=True, help="Update both lambdas and services")
@click.option("--from-source", "from_source", is_flag=True, help="Package and deploy Lambda zip from local src/")
@click.option("--lambda-s3-bucket", default="", help="S3 bucket for Lambda zip")
@click.option("--lambda-s3-key", default="", help="S3 key for Lambda zip")
@click.option("--image-tag", default="", help="ECR image tag for Lambda/ECS update")
@click.option("--region", default="us-east-1", help="AWS region")
@click.option("--profile", default=None, help="AWS profile name")
def update_cmd(
    name: str,
    update_lambdas: bool,
    update_services: bool,
    update_all: bool,
    from_source: bool,
    lambda_s3_bucket: str,
    lambda_s3_key: str,
    image_tag: str,
    region: str,
    profile: str | None,
) -> None:
    """Update a cogtainer's running services.

    If neither --lambdas nor --services is specified, updates both (same as --all).
    """
    if from_source:
        update_lambdas = True

    # If neither flag is set, update both
    if not update_lambdas and not update_services:
        update_all = True

    if update_all:
        update_lambdas = True
        update_services = True

    session, _account_id = _get_aws_session(region=region, profile=profile)

    # Get cogent list
    cogent_names = _get_cogent_names(session, name, region)
    if not cogent_names:
        click.echo(f"No cogents found for cogtainer '{name}'.")
        return

    click.echo(f"Updating cogtainer '{name}' ({len(cogent_names)} cogent(s): {', '.join(cogent_names)})...")

    if update_lambdas:
        if from_source:
            click.echo("Packaging Lambda zip from source...")
            zipfile_bytes = _build_lambda_zip()
            click.echo(f"  zip size: {len(zipfile_bytes) / 1024 / 1024:.1f} MB")

            click.echo("Uploading to Lambda functions...")
            lambda_client = session.client("lambda", region_name=region)
            suffixes = ["event-router", "executor", "dispatcher", "ingress"]
            for cogent_name in cogent_names:
                safe_name = cogent_name.replace(".", "-")
                for suffix in suffixes:
                    fn_name = f"cogtainer-{name}-{safe_name}-{suffix}"
                    try:
                        lambda_client.update_function_code(
                            FunctionName=fn_name,
                            ZipFile=zipfile_bytes,
                        )
                        click.echo(f"  {fn_name}: updated")
                    except lambda_client.exceptions.ResourceNotFoundException:
                        click.echo(f"  {fn_name}: not found (skip)")
                    except Exception as e:
                        click.echo(f"  {fn_name}: {e}")
        else:
            click.echo("Updating Lambda functions...")
            _update_lambdas(
                session, name, cogent_names, region,
                s3_bucket=lambda_s3_bucket,
                s3_key=lambda_s3_key,
                image_tag=image_tag,
            )

    if update_services:
        click.echo("Restarting ECS services...")
        _update_services(
            session, name, cogent_names, region,
            image_tag=image_tag,
        )

    click.echo("Done.")


@cli.group()
def dns() -> None:
    """Manage Cloudflare DNS for cogtainer domains."""


@dns.command("init")
@click.option("--api-token", required=True, help="Cloudflare API token")
@click.option("--account-id", required=True, help="Cloudflare account ID")
@click.option("--zone-id", required=True, help="Cloudflare zone ID")
@click.option("--profile", default=None, help="AWS profile name")
def dns_init(api_token: str, account_id: str, zone_id: str, profile: str | None) -> None:
    """Store Cloudflare API credentials in Secrets Manager."""
    from cogtainer.cloudflare import SECRET_PATH
    from cogtainer.secret_store import SecretStore

    session, _acct = _get_aws_session(profile=profile)
    store = SecretStore(session=session)
    store.put(SECRET_PATH, {
        "api_token": api_token,
        "account_id": account_id,
        "zone_id": zone_id,
    })
    click.echo(f"Stored Cloudflare credentials at {SECRET_PATH}")


@dns.command("validate-cert")
@click.option("--cert-arn", default=None, help="ACM certificate ARN (auto-detects if omitted)")
@click.option("--profile", default=None, help="AWS profile name")
@click.option("--region", default="us-east-1")
def dns_validate_cert(cert_arn: str | None, profile: str | None, region: str) -> None:
    """Add ACM certificate validation CNAME records to Cloudflare."""
    from cogtainer.cloudflare import ensure_dns_record_unproxied
    from cogtainer.deploy_config import deploy_config
    from cogtainer.secret_store import SecretStore

    session, _acct = _get_aws_session(profile=profile)
    store = SecretStore(session=session)
    acm = session.client("acm", region_name=region)

    domain = deploy_config("domain", "")
    if not domain:
        click.echo("Error: domain is not configured. Set it in deploy_config.")
        return

    if not cert_arn:
        resp = acm.list_certificates(CertificateStatuses=["PENDING_VALIDATION"])
        certs = [
            c for c in resp["CertificateSummaryList"]
            if domain in c.get("DomainName", "")
        ]
        if not certs:
            click.echo("No pending certificates found for domain.")
            return
        cert_arn = certs[0]["CertificateArn"]
        click.echo(f"Found pending cert: {cert_arn}")

    cert = acm.describe_certificate(CertificateArn=cert_arn)["Certificate"]

    for dvo in cert.get("DomainValidationOptions", []):
        rr = dvo.get("ResourceRecord")
        if not rr:
            continue
        if dvo.get("ValidationStatus") == "SUCCESS":
            click.echo(f"  {dvo['DomainName']}: already validated")
            continue

        cname_name = rr["Name"].rstrip(".")
        cname_value = rr["Value"].rstrip(".")
        click.echo(f"  Adding validation CNAME: {cname_name} -> {cname_value}")
        ensure_dns_record_unproxied(store, cname_name, cname_value, domain)
        click.echo("  Done. Validation may take a few minutes.")


@dns.command("status")
@click.option("--profile", default=None, help="AWS profile name")
@click.option("--region", default="us-east-1")
def dns_status(profile: str | None, region: str) -> None:
    """Check DNS and certificate status for the cogtainer domain."""
    import subprocess as _sp

    from cogtainer.deploy_config import deploy_config

    domain = deploy_config("domain", "")
    if not domain:
        click.echo("Error: domain is not configured. Set it in deploy_config.")
        return

    click.echo(f"Domain: {domain}")

    # Check NS records
    try:
        ns_result = _sp.run(
            ["dig", "+short", "NS", domain],
            capture_output=True, text=True, timeout=10,
        )
        ns_servers = ns_result.stdout.strip().split("\n") if ns_result.stdout.strip() else []
        click.echo(f"NS records: {', '.join(ns_servers) or '(none)'}")

        is_cloudflare = any("cloudflare" in ns for ns in ns_servers)
        is_route53 = any("awsdns" in ns for ns in ns_servers)
        if is_cloudflare:
            click.echo("  -> DNS served by Cloudflare")
        elif is_route53:
            click.echo("  -> DNS served by Route53")
    except Exception:
        click.echo("  (could not check NS records)")

    # Check ACM cert
    try:
        session, _acct = _get_aws_session(profile=profile)
        acm = session.client("acm", region_name=region)
        resp = acm.list_certificates(
            CertificateStatuses=["PENDING_VALIDATION", "ISSUED", "FAILED"],
        )
        for cert_summary in resp["CertificateSummaryList"]:
            if domain not in cert_summary.get("DomainName", ""):
                continue
            cert = acm.describe_certificate(CertificateArn=cert_summary["CertificateArn"])["Certificate"]
            click.echo(f"ACM cert ({cert['DomainName']}): {cert['Status']}")
            for dvo in cert.get("DomainValidationOptions", []):
                status = dvo.get("ValidationStatus", "UNKNOWN")
                rr = dvo.get("ResourceRecord", {})
                click.echo(f"  {dvo['DomainName']}: {status}")
                if rr and status != "SUCCESS":
                    click.echo(f"    Needs CNAME: {rr.get('Name')} -> {rr.get('Value')}")
    except Exception as e:
        click.echo(f"  ACM check failed: {e}")

    # Check Cloudflare creds
    try:
        from cogtainer.cloudflare import SECRET_PATH, list_dns_records
        from cogtainer.secret_store import SecretStore

        store = SecretStore(session=session)
        store.get(SECRET_PATH)
        click.echo("Cloudflare credentials: found")
        records = list_dns_records(store)
        click.echo(f"Cloudflare DNS records: {len(records)}")
        for r in records:
            proxy = " (proxied)" if r.get("proxied") else ""
            click.echo(f"  {r['type']:6s} {r['name']} -> {r.get('content', '')}{proxy}")
    except Exception:
        click.echo("Cloudflare credentials: NOT FOUND")
        click.echo("  Run: cogtainer dns init --api-token TOKEN --account-id ID --zone-id ZID")


@cli.command("deploy-dashboard")
@click.argument("name")
@click.option("--sha", default=None, help="Git SHA of dashboard image to deploy (default: latest)")
@click.option("--profile", default=None, help="AWS profile name")
@click.option("--region", default="us-east-1", help="AWS region")
def deploy_dashboard_cmd(
    name: str,
    sha: str | None,
    profile: str | None,
    region: str,
) -> None:
    """Deploy dashboard for a cogtainer by updating ECS image tag.

    \b
    Updates all dashboard ECS services in the cogtainer to use
    cogent-dashboard:{sha} from the shared ECR repo.
    """
    session, account_id = _get_aws_session(region=region, profile=profile)
    cogent_names = _get_cogent_names(session, name, region)
    if not cogent_names:
        click.echo(f"No cogents found for cogtainer '{name}'.")
        return

    raw_tag = sha or "latest"
    image_tag = raw_tag if raw_tag.startswith("sha-") or raw_tag == "latest" else f"sha-{raw_tag}"
    image_uri = f"{account_id}.dkr.ecr.{region}.amazonaws.com/cogent-dashboard:{image_tag}"
    click.echo(f"Deploying dashboard image {image_uri}")

    ecs_client = session.client("ecs", region_name=region)
    cluster = f"cogtainer-{name}"
    services = ecs_client.list_services(cluster=cluster)["serviceArns"]
    for svc_arn in services:
        svc_name = svc_arn.rsplit("/", 1)[-1]
        if "DashService" in svc_name or "dashboard" in svc_name:
            # Get current task def, update image, register new revision
            svc_desc = ecs_client.describe_services(cluster=cluster, services=[svc_arn])["services"][0]
            task_def = ecs_client.describe_task_definition(taskDefinition=svc_desc["taskDefinition"])["taskDefinition"]
            for c in task_def["containerDefinitions"]:
                if c.get("name") == "web":
                    c["image"] = image_uri
                    c["environment"] = [
                        e for e in c.get("environment", [])
                        if e["name"] not in ("DASHBOARD_ASSETS_S3", "DASHBOARD_DOCKER_VERSION")
                    ]
            reg_fields = [
                "family", "containerDefinitions", "taskRoleArn", "executionRoleArn",
                "networkMode", "requiresCompatibilities", "cpu", "memory",
            ]
            reg_kwargs = {k: task_def[k] for k in reg_fields if k in task_def}
            new_td = ecs_client.register_task_definition(**reg_kwargs)
            new_td_arn = new_td["taskDefinition"]["taskDefinitionArn"]
            ecs_client.update_service(
                cluster=cluster, service=svc_arn,
                taskDefinition=new_td_arn, forceNewDeployment=True,
            )
            click.echo(f"  {svc_name}: updated to {image_tag}")

    click.echo(click.style("Dashboard deployed.", fg="green"))


if __name__ == "__main__":
    cli()
