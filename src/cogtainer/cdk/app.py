"""CDK app entry point for cogtainer infrastructure (deployed in polis account)."""

from __future__ import annotations

import aws_cdk as cdk

from cogtainer.cdk.config import POLIS_ACCOUNT, POLIS_REGION, CogtainerConfig
from cogtainer.cdk.stack import CogtainerStack
from polis import naming


def main() -> None:
    app = cdk.App()
    cogent_name = app.node.try_get_context("cogent_name") or "default"
    certificate_arn = app.node.try_get_context("certificate_arn") or ""
    ecr_repo_uri = app.node.try_get_context("ecr_repo_uri") or ""
    llm_provider = app.node.try_get_context("llm_provider") or "bedrock"
    shared_db_cluster_arn = app.node.try_get_context("shared_db_cluster_arn") or ""
    shared_db_secret_arn = app.node.try_get_context("shared_db_secret_arn") or ""

    config = CogtainerConfig(
        cogent_name=cogent_name,
        ecr_repo_uri=ecr_repo_uri,
        llm_provider=llm_provider,
        shared_db_cluster_arn=shared_db_cluster_arn,
        shared_db_secret_arn=shared_db_secret_arn,
    )

    CogtainerStack(
        app,
        naming.stack_name(cogent_name),
        config=config,
        certificate_arn=certificate_arn,
        env=cdk.Environment(account=POLIS_ACCOUNT, region=POLIS_REGION),
    )

    app.synth()


if __name__ == "__main__":
    main()
