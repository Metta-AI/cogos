"""CDK app entry point for the polis stack.

Usage (polis):
    npx cdk deploy --app "python -m polis.cdk.app" -c org_id=<org_id>

Usage (cogent):
    npx cdk deploy --app "python -m polis.cdk.app" \
        -c cogent_name=<name> \
        -c shared_db_cluster_arn=<arn> \
        -c shared_db_secret_arn=<arn> \
        [-c certificate_arn=<arn>] \
        [-c shared_event_bus_name=<name>] \
        [-c shared_alb_listener_arn=<arn>] \
        [-c shared_alb_security_group_id=<id>] \
        [-c ecr_repo_uri=<uri>]
"""

from __future__ import annotations

import aws_cdk as cdk

from polis import naming
from polis.aws import DEFAULT_REGION, POLIS_ACCOUNT_ID
from polis.cdk.stacks.cogent import CogentStack
from polis.cdk.stacks.core import PolisStack
from polis.cdk.stacks.secrets import SecretsStack
from polis.config import PolisConfig, deploy_config

ORG_ID = deploy_config("org_id", "o-n7g18rzou1")


def _ctx(app: cdk.App, key: str, default: str = "") -> str:
    """Read a CDK context variable, falling back to *default*."""
    return app.node.try_get_context(key) or default


def build_app(config: PolisConfig | None = None, org_id: str = "") -> cdk.App:
    """Build the CDK app with the polis stacks."""
    config = config or PolisConfig()
    app = cdk.App()

    env = cdk.Environment(account=POLIS_ACCOUNT_ID, region=DEFAULT_REGION)
    cogent_name = _ctx(app, "cogent_name")

    if cogent_name:
        # Deploy a per-cogent stack
        CogentStack(
            app,
            naming.stack_name(cogent_name),
            cogent_name=cogent_name,
            domain=config.domain,
            shared_db_cluster_arn=_ctx(app, "shared_db_cluster_arn"),
            shared_db_secret_arn=_ctx(app, "shared_db_secret_arn"),
            shared_event_bus_name=_ctx(
                app, "shared_event_bus_name", naming.shared_event_bus_name()
            ),
            shared_alb_listener_arn=_ctx(app, "shared_alb_listener_arn"),
            shared_alb_security_group_id=_ctx(app, "shared_alb_security_group_id"),
            certificate_arn=_ctx(app, "certificate_arn"),
            ecr_repo_uri=_ctx(app, "ecr_repo_uri"),
            env=env,
        )
    else:
        # Deploy the shared polis infrastructure
        org_id = org_id or _ctx(app, "org_id", ORG_ID)
        PolisStack(
            app, naming.polis_stack_name(), config=config, org_id=org_id, env=env
        )
        SecretsStack(app, naming.secrets_stack_name(), org_id=org_id, env=env)

    return app


if __name__ == "__main__":
    app = build_app()
    app.synth()
