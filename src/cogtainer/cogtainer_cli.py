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
    load_config,
)


def _config_path() -> Path:
    """Return the config file path from env or default."""
    env = os.environ.get("COGOS_CONFIG_PATH")
    if env:
        return Path(env)
    return Path.home() / ".cogos" / "cogtainers.yml"


def _load() -> CogtainersConfig:
    """Load the cogtainers config."""
    return load_config(_config_path())


def _save_config(cfg: CogtainersConfig) -> None:
    """Write CogtainersConfig to YAML."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(cfg.model_dump(exclude_none=True), f, default_flow_style=False)


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
@click.option("--data-dir", default=None)
@click.option("--domain", default=None)
@click.option("--profile", default=None, help="AWS profile name (for aws type)")
def create(
    name: str,
    ctype: str,
    llm_provider: str | None,
    llm_model: str | None,
    llm_api_key_env: str | None,
    region: str | None,
    data_dir: str | None,
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
            _save_config(cfg)
            click.echo(f"Updated cogtainer '{name}' (account_id={existing.account_id}).")
            return
        click.echo(f"Cogtainer '{name}' already exists.")
        raise SystemExit(1)

    llm = LLMConfig(
        provider=llm_provider or "bedrock",
        model=llm_model or "",
        api_key_env=llm_api_key_env or "",
    )

    account_id = None

    if ctype == "aws":
        if not region:
            region = "us-east-1"
        account_id = _cdk_create_account(name, region=region, profile=profile)

    # Default data_dir for local/docker
    if ctype in ("local", "docker") and not data_dir:
        data_dir = str(Path.home() / ".cogos" / "cogtainers" / name)

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
        data_dir=data_dir,
        llm=llm,
        dashboard_be_port=be_port,
        dashboard_fe_port=fe_port,
    )
    cfg.cogtainers[name] = entry

    # Set as default if it's the only cogtainer
    if len(cfg.cogtainers) == 1:
        cfg.defaults.cogtainer = name

    # Create data dir for local/docker
    if ctype in ("local", "docker") and data_dir:
        Path(data_dir).mkdir(parents=True, exist_ok=True)

    _save_config(cfg)
    click.echo(f"Created cogtainer '{name}' (type={ctype}, account_id={account_id}).")


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

    del cfg.cogtainers[name]

    if cfg.defaults.cogtainer == name:
        cfg.defaults.cogtainer = None

    _save_config(cfg)
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
@click.argument("name")
def select(name: str) -> None:
    """Select a cogtainer by writing COGTAINER to .env."""
    cfg = _load()

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
    if entry.data_dir:
        click.echo(f"  data_dir: {entry.data_dir}")
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
    elif entry.data_dir:
        out = Path(entry.data_dir) / "docker-compose.yml"
    else:
        out = Path("docker-compose.yml")

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
        if len(cfg.cogtainers) == 1:
            cfg.defaults.cogtainer = "aws"
        _save_config(cfg)
        click.echo(f"Created cogtainer 'aws' (account={account_id}, region={region}).")
    else:
        click.echo("Cogtainer 'aws' already exists, keeping existing config.")

    click.echo(f"Discovered {len(cogent_names)} cogent(s):")
    for name in cogent_names:
        click.echo(f"  - {name}")


def _get_cogent_names(session, cogtainer_name: str, region: str) -> list[str]:
    """Get cogent names for a cogtainer from DynamoDB cogent-status table."""
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

    return sorted(
        item["cogent_name"]
        for item in items
        if item.get("cogent_name")
    )


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
    suffixes = ["event-router", "executor", "dispatcher"]

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
    cluster = f"cogent-{cogtainer_name}"

    # Try default cluster name, fall back to cogtainer
    try:
        ecs_client.describe_clusters(clusters=[cluster])["clusters"]
    except Exception:
        cluster = naming.cluster_name()

    service_types = ["dashboard", "discord"]

    for cogent_name in cogent_names:
        safe_name = cogent_name.replace(".", "-")
        for stype in service_types:
            service_name = f"cogent-{safe_name}-{stype}"
            try:
                ecs_client.update_service(
                    cluster=cluster,
                    service=service_name,
                    forceNewDeployment=True,
                )
                click.echo(f"  {service_name}: restarted")
            except ecs_client.exceptions.ServiceNotFoundException:
                click.echo(f"  {service_name}: not found (skip)")
            except Exception as e:
                click.echo(f"  {service_name}: {e}")


@cli.command("update")
@click.argument("name")
@click.option("--lambdas", "update_lambdas", is_flag=True, help="Update Lambda function code")
@click.option("--services", "update_services", is_flag=True, help="Restart ECS services with new image")
@click.option("--all", "update_all", is_flag=True, help="Update both lambdas and services")
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
    lambda_s3_bucket: str,
    lambda_s3_key: str,
    image_tag: str,
    region: str,
    profile: str | None,
) -> None:
    """Update a cogtainer's running services.

    If neither --lambdas nor --services is specified, updates both (same as --all).
    """
    # If neither flag is set, update both
    if not update_lambdas and not update_services:
        update_all = True

    if update_all:
        update_lambdas = True
        update_services = True

    session, _account_id = _get_aws_session(region=region, profile=profile)

    # Get cogent list from DynamoDB
    cogent_names = _get_cogent_names(session, name, region)
    if not cogent_names:
        click.echo(f"No cogents found for cogtainer '{name}'.")
        return

    click.echo(f"Updating cogtainer '{name}' ({len(cogent_names)} cogent(s))...")

    if update_lambdas:
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

    domain = deploy_config("domain", "softmax-cogents.com")

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

    domain = deploy_config("domain", "softmax-cogents.com")

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


if __name__ == "__main__":
    cli()
