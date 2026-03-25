"""AwsRuntime — run cogents on AWS (S3, DynamoDB, Lambda, EventBridge)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from cogtainer.config import CogtainerEntry
from cogtainer.llm.provider import LLMProvider
from cogtainer.runtime.base import CogtainerRuntime
from cogtainer.secrets import SecretsProvider

logger = logging.getLogger(__name__)

_LEGACY_STATUS_TABLE = "cogent-status"


class AwsRuntime(CogtainerRuntime):
    """Cogtainer runtime backed by AWS services."""

    def __init__(
        self,
        entry: CogtainerEntry,
        llm: LLMProvider,
        session: Any,
        cogtainer_name: str = "",
    ) -> None:
        self._entry = entry
        self._llm = llm
        self._session = session
        self._region = entry.region or "us-east-1"
        self._cogtainer_name = cogtainer_name
        # New cogtainers use cogtainer-{name}-status, legacy uses cogent-status
        self._status_table = (
            f"cogtainer-{cogtainer_name}-status" if cogtainer_name else _LEGACY_STATUS_TABLE
        )
        self._db_info_cache: dict[str, str] = {}

        from cogtainer.secrets import AwsSecretsProvider

        self._secrets = AwsSecretsProvider(region=self._region, session=session)

    def _safe(self, name: str) -> str:
        return name.replace(".", "-")

    def _get_stack_outputs(self) -> dict[str, str]:
        """Get CloudFormation stack outputs for this cogtainer."""
        cf = self._session.client("cloudformation", region_name=self._region)
        stack_name = f"cogtainer-{self._cogtainer_name}"
        try:
            resp = cf.describe_stacks(StackName=stack_name)
            outputs = resp["Stacks"][0].get("Outputs", [])
            return {o["OutputKey"]: o["OutputValue"] for o in outputs}
        except Exception:
            return {}

    def _get_db_info(self) -> dict[str, str]:
        """Get DB cluster ARN and secret ARN from stack outputs."""
        if not self._db_info_cache:
            outputs = self._get_stack_outputs()
            self._db_info_cache = {
                "cluster_arn": outputs.get("DbClusterArn", ""),
                "secret_arn": outputs.get("DbSecretArn", ""),
            }
        return self._db_info_cache

    # ── Repository ───────────────────────────────────────────

    def get_repository(self, cogent_name: str) -> Any:
        from cogos.db.repository import RdsDataApiRepository

        db_info = self._get_db_info()
        cluster_arn = db_info.get("cluster_arn") or os.environ["DB_CLUSTER_ARN"]
        secret_arn = db_info.get("secret_arn") or os.environ["DB_SECRET_ARN"]
        db_name = os.environ.get("DB_NAME") or f"cogent_{self._safe(cogent_name).replace('-', '_')}"

        client = self._session.client("rds-data", region_name=self._region)

        def _nudge(queue_url: str, body: str) -> None:
            sqs = self._session.client("sqs", region_name=self._region)
            import time as _time
            sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=body,
                MessageGroupId="ingress-wake",
                MessageDeduplicationId=str(int(_time.time())),
            )

        return RdsDataApiRepository(
            client=client,
            resource_arn=cluster_arn,
            secret_arn=secret_arn,
            database=db_name,
            region=self._region,
            nudge_callback=_nudge,
        )

    # ── LLM ──────────────────────────────────────────────────

    def converse(
        self,
        *,
        messages: list[dict],
        system: list[dict],
        tool_config: dict,
        model: str | None = None,
    ) -> dict:
        return self._llm.converse(
            messages=messages,
            system=system,
            tool_config=tool_config,
            model=model,
        )

    # ── File storage ─────────────────────────────────────────

    def _prefixed_key(self, cogent_name: str, key: str) -> str:
        """Prefix a key with the cogent's safe name for the shared bucket."""
        from cogtainer.naming import safe
        return f"{safe(cogent_name)}/{key}"

    def put_file(self, cogent_name: str, key: str, data: bytes) -> str:
        from cogtainer.naming import bucket_name

        s3 = self._session.client("s3", region_name=self._region)
        prefixed = self._prefixed_key(cogent_name, key)
        s3.put_object(
            Bucket=bucket_name(cogent_name),
            Key=prefixed,
            Body=data,
        )
        return key

    def get_file(self, cogent_name: str, key: str) -> bytes:
        from cogtainer.naming import bucket_name

        s3 = self._session.client("s3", region_name=self._region)
        prefixed = self._prefixed_key(cogent_name, key)
        resp = s3.get_object(
            Bucket=bucket_name(cogent_name),
            Key=prefixed,
        )
        return resp["Body"].read()

    # ── Events ───────────────────────────────────────────────

    def emit_event(self, cogent_name: str, event: dict) -> None:
        from cogtainer.naming import safe

        eb = self._session.client("events", region_name=self._region)
        safe_name = safe(cogent_name)
        eb.put_events(
            Entries=[
                {
                    "Source": f"cogent.{cogent_name}",
                    "DetailType": event.get("type", "cogent.event"),
                    "Detail": json.dumps(event),
                    "EventBusName": f"cogent-{safe_name}",
                },
            ],
        )

    # ── Executor ─────────────────────────────────────────────

    def spawn_executor(self, cogent_name: str, process_id: str) -> None:
        from cogtainer.naming import safe

        lam = self._session.client("lambda", region_name=self._region)
        safe_name = safe(cogent_name)
        fn_name = f"cogtainer-{self._cogtainer_name}-{safe_name}-executor"
        lam.invoke(
            FunctionName=fn_name,
            InvocationType="Event",
            Payload=json.dumps({"process_id": process_id}).encode(),
        )

    # ── Cogent lifecycle ─────────────────────────────────────

    def list_cogents(self) -> list[str]:
        ddb = self._session.resource("dynamodb", region_name=self._region)
        table = ddb.Table(self._status_table)
        resp = table.scan()
        items = resp.get("Items", [])
        return sorted(item["cogent_name"] for item in items if "cogent_name" in item)

    def create_cogent(self, name: str) -> None:
        """Register a cogent in the status table, create its database, and deploy CDK stack."""
        safe = self._safe(name)
        db_name = f"cogent_{safe.replace('-', '_')}"
        db_info = self._get_db_info()

        # 1. Create database on the cogtainer's Aurora cluster
        rds = self._session.client("rds-data", region_name=self._region)
        try:
            rds.execute_statement(
                resourceArn=db_info["cluster_arn"],
                secretArn=db_info["secret_arn"],
                database="postgres",
                sql=f"CREATE DATABASE {db_name}",
            )
            logger.info("Created database %s", db_name)
        except Exception as e:
            if "already exists" in str(e):
                logger.info("Database %s already exists", db_name)
            else:
                raise

        # 2. Register in status table
        ddb = self._session.resource("dynamodb", region_name=self._region)
        import time
        ddb.Table(self._status_table).put_item(
            Item={
                "cogent_name": name,
                "db_name": db_name,
                "database": {
                    "cluster_arn": db_info["cluster_arn"],
                    "secret_arn": db_info["secret_arn"],
                    "db_name": db_name,
                },
                "updated_at": int(time.time()),
            }
        )

        # 3. Apply schema using the cogtainer session's RDS client
        from cogos.db.migrations import apply_schema_with_client
        rds_client = self._session.client("rds-data", region_name=self._region)
        apply_schema_with_client(
            rds_client, db_info["cluster_arn"], db_info["secret_arn"], db_name
        )
        logger.info("Schema applied to %s", db_name)

        # 4. Ensure dashboard frontend assets exist in the shared sessions bucket
        self._ensure_frontend_assets()

        # 5. Deploy per-cogent CDK stack
        self._deploy_cogent_stack(name)

        # 6. Ensure Cloudflare DNS record points to the ALB
        self._ensure_dns_record(name)

    def _ensure_frontend_assets(self) -> None:
        """Ensure dashboard/frontend.tar.gz exists in the shared sessions bucket.

        Copies from another cogent's legacy bucket or the CI artifacts bucket
        if the shared bucket doesn't have it yet.
        """
        bucket = f"cogtainer-{self._cogtainer_name}-sessions"
        s3_key = "dashboard/frontend.tar.gz"
        s3 = self._session.client("s3", region_name=self._region)

        # Check if already present
        try:
            s3.head_object(Bucket=bucket, Key=s3_key)
            logger.info("Frontend assets already present in %s/%s", bucket, s3_key)
            return
        except Exception:
            pass

        # Try to copy from CI artifacts bucket
        try:
            ci_bucket = "cogtainer-ci-artifacts"
            # Find the latest dashboard artifact
            resp = s3.list_objects_v2(Bucket=ci_bucket, Prefix="dashboard/", MaxKeys=100)
            # Look for dashboard/{sha}/frontend.tar.gz — pick the most recent
            artifacts = [
                obj for obj in resp.get("Contents", [])
                if obj["Key"].endswith("/frontend.tar.gz")
            ]
            if artifacts:
                latest = max(artifacts, key=lambda o: o["LastModified"])
                logger.info("Copying frontend assets from CI: %s", latest["Key"])
                s3.copy_object(
                    CopySource={"Bucket": ci_bucket, "Key": latest["Key"]},
                    Bucket=bucket,
                    Key=s3_key,
                )
                return
        except Exception:
            logger.debug("Could not copy from CI artifacts", exc_info=True)

        # Try to copy from any existing cogent's legacy per-cogent bucket
        try:
            resp = s3.list_buckets()
            for b in resp.get("Buckets", []):
                bn = b["Name"]
                if bn.startswith("cogtainer-") and bn.endswith("-sessions") and bn != bucket:
                    try:
                        s3.head_object(Bucket=bn, Key=s3_key)
                        logger.info("Copying frontend assets from %s", bn)
                        s3.copy_object(
                            CopySource={"Bucket": bn, "Key": s3_key},
                            Bucket=bucket,
                            Key=s3_key,
                        )
                        return
                    except Exception:
                        continue
        except Exception:
            logger.debug("Could not copy from existing buckets", exc_info=True)

        logger.warning(
            "No frontend assets found to seed %s/%s — "
            "run 'cogtainer update dashboard' after deploy",
            bucket, s3_key,
        )

    def _ensure_dns_record(self, cogent_name: str) -> None:
        """Create a Cloudflare DNS CNAME for the cogent's dashboard subdomain."""
        try:
            from cogtainer.cloudflare import ensure_dns_record
            from cogtainer.secret_store import SecretStore

            store = SecretStore(session=self._session, region=self._region)
            outputs = self._get_stack_outputs()
            alb_dns = outputs.get("AlbDns", "")
            domain = outputs.get("Domain", "")
            if not alb_dns or not domain:
                logger.warning("Cannot create DNS: missing AlbDns or Domain in stack outputs")
                return

            safe = self._safe(cogent_name)
            ensure_dns_record(store, safe, alb_dns, domain)
            logger.info("DNS record created: %s.%s -> %s", safe, domain, alb_dns)
        except Exception:
            logger.warning("Could not create DNS record for %s (create manually)", cogent_name, exc_info=True)

    def get_secrets_provider(self) -> SecretsProvider:
        return self._secrets

    def _deploy_cogent_stack(self, cogent_name: str) -> None:
        """Deploy the per-cogent CDK stack (Lambdas, ECS, EventBridge, etc.)."""
        import os
        import subprocess

        from cogtainer.cogtainer_cli import resolve_org_profile

        safe_name = self._safe(cogent_name)
        stack_name = f"cogtainer-{self._cogtainer_name}-{safe_name}"
        cmd = [
            "npx", "cdk", "deploy", stack_name,
            "--app", "python -m cogtainer.cdk.app",
            "-c", f"cogtainer_name={self._cogtainer_name}",
            "-c", f"cogent_name={cogent_name}",
            "-c", "dashboard_sha=latest",
            "-c", "bridge_image_tag=executor-latest",
            "--require-approval", "never",
        ]
        env = {**os.environ, "AWS_PROFILE": resolve_org_profile()}
        logger.info("Deploying CDK stack %s", stack_name)
        result = subprocess.run(cmd, capture_output=False, env=env)
        if result.returncode != 0:
            raise RuntimeError(f"CDK deploy failed for {stack_name}")

    def destroy_cogent(self, name: str) -> None:
        """Destroy a cogent and all its per-cogent resources.

        Tears down: CDK stack (Lambdas, SQS, IAM, EventBridge, ECS services),
        PostgreSQL database, DNS record, S3 data prefix, and DynamoDB entry.
        Does NOT touch shared resources (Aurora cluster, sessions bucket,
        ALB, VPC, ECS cluster, EventBridge bus, DynamoDB table).
        """
        import os
        import subprocess

        safe = self._safe(name)

        # Pre-fetch cogtainer-level stack outputs (domain, etc.) before any teardown
        outputs = self._get_stack_outputs()
        domain = outputs.get("Domain", "")

        # 1. Destroy per-cogent CDK stack
        logger.info("Destroying CDK stack for cogent %s", name)
        try:
            from cogtainer.cogtainer_cli import resolve_org_profile

            stack_name = f"cogtainer-{self._cogtainer_name}-{safe}"
            cmd = [
                "npx", "cdk", "destroy", stack_name,
                "--app", "python -m cogtainer.cdk.app",
                "-c", f"cogtainer_name={self._cogtainer_name}",
                "-c", f"cogent_name={name}",
                "--force",
            ]
            env = {**os.environ, "AWS_PROFILE": resolve_org_profile()}
            result = subprocess.run(cmd, capture_output=False, env=env)
            if result.returncode != 0:
                logger.warning("CDK destroy failed for %s (may not exist)", stack_name)
        except Exception:
            logger.warning("Could not destroy CDK stack for %s", name, exc_info=True)

        # 2. Drop per-cogent PostgreSQL database
        logger.info("Dropping database for cogent %s", name)
        try:
            db_info = self._get_db_info()
            db_name = f"cogent_{safe.replace('-', '_')}"
            rds = self._session.client("rds-data", region_name=self._region)
            # Terminate active connections first
            rds.execute_statement(
                resourceArn=db_info["cluster_arn"],
                secretArn=db_info["secret_arn"],
                database="postgres",
                sql=(
                    f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    f"WHERE datname = '{db_name}' AND pid <> pg_backend_pid()"
                ),
            )
            rds.execute_statement(
                resourceArn=db_info["cluster_arn"],
                secretArn=db_info["secret_arn"],
                database="postgres",
                sql=f"DROP DATABASE IF EXISTS {db_name}",
            )
            logger.info("Dropped database %s", db_name)
        except Exception:
            logger.warning("Could not drop database for %s", name, exc_info=True)

        # 3. Delete Cloudflare DNS record
        logger.info("Deleting DNS record for cogent %s", name)
        try:
            # cloudflare module reads COGTAINER env var at import time
            os.environ.setdefault("COGTAINER", self._cogtainer_name)
            from cogtainer.cloudflare import delete_dns_record
            from cogtainer.secret_store import SecretStore

            store = SecretStore(session=self._session, region=self._region)
            if domain:
                delete_dns_record(store, safe, domain)
                logger.info("Deleted DNS record for %s.%s", safe, domain)
            else:
                logger.warning("No domain in stack outputs, skipping DNS cleanup")
        except Exception:
            logger.warning("Could not delete DNS record for %s", name, exc_info=True)

        # 4. Clean up S3 data prefix (per-cogent only, not shared dashboard/)
        logger.info("Cleaning up S3 data for cogent %s", name)
        try:
            bucket = f"cogtainer-{self._cogtainer_name}-sessions"
            s3 = self._session.client("s3", region_name=self._region)
            prefix = f"{safe}/"
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                objects = page.get("Contents", [])
                if objects:
                    s3.delete_objects(
                        Bucket=bucket,
                        Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
                    )
            logger.info("Cleaned up S3 prefix %s in %s", prefix, bucket)
        except Exception:
            logger.warning("Could not clean up S3 data for %s", name, exc_info=True)

        # 5. Remove from DynamoDB status table
        logger.info("Removing cogent %s from status table", name)
        ddb = self._session.resource("dynamodb", region_name=self._region)
        ddb.Table(self._status_table).delete_item(Key={"cogent_name": name})

    # ── Queue messaging ──────────────────────────────────────

    def send_queue_message(self, queue_name: str, body: str, *, dedup_id: str | None = None) -> None:
        sqs = self._session.client("sqs", region_name=self._region)
        url = self.get_queue_url(queue_name)
        kwargs: dict = {"QueueUrl": url, "MessageBody": body}
        if dedup_id:
            kwargs["MessageDeduplicationId"] = dedup_id
            kwargs["MessageGroupId"] = "default"
        sqs.send_message(**kwargs)

    def get_queue_url(self, queue_name: str) -> str:
        sts = self._session.client("sts", region_name=self._region)
        account_id = sts.get_caller_identity()["Account"]
        return f"https://sqs.{self._region}.amazonaws.com/{account_id}/{queue_name}"

    # ── Blob URLs + email ────────────────────────────────────

    def get_file_url(self, cogent_name: str, key: str, expires_in: int = 604800) -> str:
        from cogtainer.naming import bucket_name
        s3 = self._session.client("s3", region_name=self._region)
        prefixed = self._prefixed_key(cogent_name, key)
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name(cogent_name), "Key": prefixed},
            ExpiresIn=expires_in,
        )

    def send_email(self, *, source: str, to: str, subject: str, body: str, reply_to: str | None = None) -> str:
        ses = self._session.client("ses", region_name=self._region)
        kwargs: dict = {
            "Source": source,
            "Destination": {"ToAddresses": [to]},
            "Message": {
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body}},
            },
        }
        if reply_to:
            kwargs["ReplyToAddresses"] = [reply_to]
        resp = ses.send_email(**kwargs)
        return resp["MessageId"]

    def verify_email_domain(self, domain: str) -> bool:
        ses = self._session.client("ses", region_name=self._region)
        resp = ses.get_identity_verification_attributes(Identities=[domain])
        attrs = resp.get("VerificationAttributes", {}).get(domain, {})
        return attrs.get("VerificationStatus") == "Success"

    def get_bedrock_client(self) -> Any:
        import boto3
        from botocore.config import Config as BotoConfig
        return boto3.client(
            "bedrock-runtime",
            region_name=self._region,
            config=BotoConfig(retries={"max_attempts": 12, "mode": "adaptive"}),
        )

    def get_session(self) -> Any:
        return self._session

    def get_dynamodb_resource(self, region: str | None = None) -> Any:
        return self._session.resource("dynamodb", region_name=region or self._region)

    def get_sqs_client(self, region: str | None = None) -> Any:
        return self._session.client("sqs", region_name=region or self._region)

    def get_s3_client(self, region: str | None = None) -> Any:
        return self._session.client("s3", region_name=region or self._region)

    def get_ecs_client(self, region: str | None = None) -> Any:
        return self._session.client("ecs", region_name=region or self._region)

    def get_rds_data_client(self, region: str | None = None) -> Any:
        return self._session.client("rds-data", region_name=region or self._region)
