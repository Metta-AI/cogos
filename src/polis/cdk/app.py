"""CDK app entry point for the polis stack.

Usage: npx cdk deploy --app "python -m polis.cdk.app" -c org_id=<org_id>
"""

from __future__ import annotations

import aws_cdk as cdk

from polis.cdk.stacks.core import PolisStack
from polis.cdk.stacks.dashboard import DashboardStack
from polis.cdk.stacks.secrets import SecretsStack
from polis.config import PolisConfig


ORG_ID = "o-n7g18rzou1"
POLIS_ACCOUNT = "901289084804"
REGION = "us-east-1"


def build_app(config: PolisConfig | None = None, org_id: str = "") -> cdk.App:
    """Build the CDK app with the polis stacks."""
    config = config or PolisConfig()
    app = cdk.App()

    org_id = org_id or app.node.try_get_context("org_id") or ORG_ID
    env = cdk.Environment(account=POLIS_ACCOUNT, region=REGION)

    PolisStack(app, "cogent-polis", config=config, org_id=org_id, env=env)
    SecretsStack(app, "cogent-secrets", org_id=org_id, env=env)

    # Per-cogent dashboard stacks (only when cogent_name context is provided)
    cogent_name = app.node.try_get_context("cogent_name") or ""
    if cogent_name:
        safe_name = cogent_name.replace(".", "-")
        DashboardStack(
            app,
            f"cogent-{safe_name}-dashboard",
            config=config,
            cogent_name=cogent_name,
            certificate_arn=app.node.try_get_context("certificate_arn") or "",
            brain_account_id=app.node.try_get_context("brain_account_id") or "",
            db_cluster_arn=app.node.try_get_context("db_cluster_arn") or "",
            db_secret_arn=app.node.try_get_context("db_secret_arn") or "",
            event_bus_name=app.node.try_get_context("event_bus_name") or "",
            sessions_bucket_name=app.node.try_get_context("sessions_bucket_name") or "",
            env=env,
        )

    return app


if __name__ == "__main__":
    app = build_app()
    app.synth()
