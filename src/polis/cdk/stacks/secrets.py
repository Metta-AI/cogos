"""Secrets CDK stack: rotation Lambda and IAM for cross-account secret access."""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    Duration,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from constructs import Construct

ROTATION_HANDLER_DIR = Path(__file__).resolve().parent.parent.parent / "secrets" / "rotation"


class SecretsStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        org_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Rotation Lambda ---
        self.rotation_fn = lambda_.Function(
            self,
            "RotationLambda",
            function_name="cogent-secret-rotation",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(ROTATION_HANDLER_DIR)),
            timeout=Duration.seconds(60),
        )

        # Rotation lambda needs to read/write secrets
        self.rotation_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:PutSecretValue",
                    "secretsmanager:DescribeSecret",
                    "secretsmanager:UpdateSecretVersionStage",
                ],
                resources=[f"arn:aws:secretsmanager:*:{cdk.Aws.ACCOUNT_ID}:secret:cogent/*"],
            )
        )

        # Allow Secrets Manager to invoke the rotation lambda
        self.rotation_fn.add_permission(
            "SecretsManagerInvoke",
            principal=iam.ServicePrincipal("secretsmanager.amazonaws.com"),  # type: ignore[arg-type]
        )

        # --- Cross-account secrets reader role ---
        self.secrets_reader_role = iam.Role(
            self,
            "SecretsReaderRole",
            role_name="cogent-secrets-reader",
            assumed_by=iam.OrganizationPrincipal(org_id),  # type: ignore[arg-type]
        )

        self.secrets_reader_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[f"arn:aws:secretsmanager:*:{cdk.Aws.ACCOUNT_ID}:secret:cogent/*"],
            )
        )
        self.secrets_reader_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:ListSecrets"],
                resources=["*"],
            )
        )

        # --- Outputs ---
        cdk.CfnOutput(self, "RotationLambdaArn", value=self.rotation_fn.function_arn)
        cdk.CfnOutput(self, "SecretsReaderRoleArn", value=self.secrets_reader_role.role_arn)
