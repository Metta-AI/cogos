"""CDK app entry point for brain infrastructure (deployed in polis account)."""

from __future__ import annotations

import aws_cdk as cdk

from brain.cdk.config import BrainConfig, POLIS_ACCOUNT, POLIS_REGION
from brain.cdk.stack import BrainStack


def main() -> None:
    app = cdk.App()
    cogent_name = app.node.try_get_context("cogent_name") or "default"
    certificate_arn = app.node.try_get_context("certificate_arn") or ""
    ecr_repo_uri = app.node.try_get_context("ecr_repo_uri") or ""

    config = BrainConfig(
        cogent_name=cogent_name,
        ecr_repo_uri=ecr_repo_uri,
    )

    BrainStack(
        app,
        f"cogent-{cogent_name.replace('.', '-')}-brain",
        config=config,
        certificate_arn=certificate_arn,
        env=cdk.Environment(account=POLIS_ACCOUNT, region=POLIS_REGION),
    )

    app.synth()


if __name__ == "__main__":
    main()
