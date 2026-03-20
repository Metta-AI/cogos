"""CDK app entry point for cogtainer stacks.

Usage (create account in management account):
    npx cdk deploy --app "python -m cogtainer.cdk.app" \
        -c cogtainer_name=<name> -c stage=account

Usage (cogtainer infra, deployed to cogtainer account):
    npx cdk deploy --app "python -m cogtainer.cdk.app" -c cogtainer_name=<name>

Usage (cogent within cogtainer):
    npx cdk deploy --app "python -m cogtainer.cdk.app" \
        -c cogtainer_name=<name> -c cogent_name=<cogent>
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION", "1")

import aws_cdk as cdk

from cogtainer.cdk.stacks.account_stack import AccountStack
from cogtainer.cdk.stacks.cogent_stack import CogentStack
from cogtainer.cdk.stacks.cogtainer_stack import CogtainerStack
from cogtainer.config import CogtainerEntry, load_config


def _ctx(app: cdk.App, key: str, default: str = "") -> str:
    """Read a CDK context variable, falling back to *default*."""
    return app.node.try_get_context(key) or default


def build_app() -> cdk.App:
    """Build the CDK app with cogtainer stacks."""
    app = cdk.App()

    cogtainer_name = _ctx(app, "cogtainer_name")
    if not cogtainer_name:
        print("ERROR: -c cogtainer_name=<name> is required", file=sys.stderr)
        sys.exit(1)

    stage = _ctx(app, "stage")

    # Stage: account — deploy to management account to create the child account
    if stage == "account":
        AccountStack(
            app,
            f"cogtainer-{cogtainer_name}-account",
            cogtainer_name=cogtainer_name,
            env=cdk.Environment(region=_ctx(app, "region", "us-east-1")),
        )
        return app

    cfg = load_config()
    entry: CogtainerEntry | None = cfg.cogtainers.get(cogtainer_name)
    if entry is None:
        print(
            f"ERROR: cogtainer '{cogtainer_name}' not found in cogtainers.yml",
            file=sys.stderr,
        )
        sys.exit(1)

    if entry.type != "aws":
        print(
            f"ERROR: cogtainer '{cogtainer_name}' is type '{entry.type}', "
            "CDK only applies to 'aws' cogtainers",
            file=sys.stderr,
        )
        sys.exit(1)

    env = cdk.Environment(
        account=entry.account_id or "",
        region=entry.region or "us-east-1",
    )

    cogent_name = _ctx(app, "cogent_name")

    if cogent_name:
        # Auto-resolve cogtainer stack outputs if not provided via context
        db_cluster_arn = _ctx(app, "db_cluster_arn")
        db_secret_arn = _ctx(app, "db_secret_arn")
        event_bus_name = _ctx(app, "event_bus_name", f"cogtainer-{cogtainer_name}")
        alb_listener_arn = _ctx(app, "alb_listener_arn")
        alb_security_group_id = _ctx(app, "alb_security_group_id")
        certificate_arn = _ctx(app, "certificate_arn")
        ecr_repo_uri = _ctx(app, "ecr_repo_uri")

        if not db_cluster_arn or not db_secret_arn:
            import boto3
            try:
                org_session = boto3.Session()
                region = entry.region or "us-east-1"
                sts = org_session.client("sts")
                role_arn = f"arn:aws:iam::{entry.account_id}:role/OrganizationAccountAccessRole"
                creds = sts.assume_role(RoleArn=role_arn, RoleSessionName="cdk-resolve")["Credentials"]
                session = boto3.Session(
                    aws_access_key_id=creds["AccessKeyId"],
                    aws_secret_access_key=creds["SecretAccessKey"],
                    aws_session_token=creds["SessionToken"],
                    region_name=region,
                )
                cf = session.client("cloudformation", region_name=region)
                resp = cf.describe_stacks(StackName=f"cogtainer-{cogtainer_name}")
                outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}
                db_cluster_arn = db_cluster_arn or outputs.get("DbClusterArn", "")
                db_secret_arn = db_secret_arn or outputs.get("DbSecretArn", "")
                event_bus_name = event_bus_name or outputs.get("EventBusName", f"cogtainer-{cogtainer_name}")
                ecr_repo_uri = ecr_repo_uri or outputs.get("ECRRepositoryUri", "")
                alb_listener_arn = alb_listener_arn or outputs.get("HttpsListenerArn", "")
                alb_security_group_id = alb_security_group_id or outputs.get("AlbSecurityGroupId", "")
                certificate_arn = certificate_arn or outputs.get("WildcardCertArn", "")
            except Exception as e:
                print(f"WARNING: Could not resolve cogtainer stack outputs: {e}", file=sys.stderr)

        from cogtainer.naming import safe as _safe
        safe_cogent = _safe(cogent_name)
        CogentStack(
            app,
            f"cogtainer-{cogtainer_name}-{safe_cogent}",
            cogtainer_name=cogtainer_name,
            cogent_name=cogent_name,
            domain=entry.domain or "",
            db_cluster_arn=db_cluster_arn,
            db_secret_arn=db_secret_arn,
            event_bus_name=event_bus_name,
            alb_listener_arn=alb_listener_arn,
            alb_security_group_id=alb_security_group_id,
            certificate_arn=certificate_arn,
            ecr_repo_uri=ecr_repo_uri,
            env=env,
        )
    else:
        # Deploy cogtainer-level shared infrastructure
        CogtainerStack(
            app,
            f"cogtainer-{cogtainer_name}",
            cogtainer_name=cogtainer_name,
            cogtainer_entry=entry,
            env=env,
        )

    return app


if __name__ == "__main__":
    app = build_app()
    app.synth()
