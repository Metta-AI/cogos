"""AwsRuntime — run cogents on AWS (S3, DynamoDB, Lambda, EventBridge)."""

from __future__ import annotations

import json
import logging
from typing import Any

from cogtainer.config import CogtainerEntry
from cogtainer.llm.provider import LLMProvider
from cogtainer.runtime.base import CogtainerRuntime

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
        # New cogtainers use cogtainer-{name}-status, legacy polis uses cogent-status
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
        from cogos.db.repository import Repository

        safe = self._safe(cogent_name)
        db_name = f"cogent_{safe.replace('-', '_')}"

        # For new cogtainers, get DB ARNs from stack outputs
        # For legacy polis, get from DynamoDB cogent-status table
        if self._cogtainer_name:
            db_info = self._get_db_info()
            cluster_arn = db_info["cluster_arn"]
            secret_arn = db_info["secret_arn"]
        else:
            ddb = self._session.resource("dynamodb", region_name=self._region)
            item = (
                ddb.Table(_LEGACY_STATUS_TABLE)
                .get_item(Key={"cogent_name": cogent_name})
                .get("Item", {})
            )
            db_sub = item.get("database", {})
            cluster_arn = db_sub.get("cluster_arn", "")
            secret_arn = db_sub.get("secret_arn", "")
            db_name = db_sub.get("db_name", db_name)

        client = self._session.client("rds-data", region_name=self._region)
        return Repository(
            client=client,
            resource_arn=cluster_arn,
            secret_arn=secret_arn,
            database=db_name,
            region=self._region,
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

    def put_file(self, cogent_name: str, key: str, data: bytes) -> str:
        from cogtainer.naming import bucket_name

        s3 = self._session.client("s3", region_name=self._region)
        s3.put_object(
            Bucket=bucket_name(cogent_name),
            Key=key,
            Body=data,
        )
        return key

    def get_file(self, cogent_name: str, key: str) -> bytes:
        from cogtainer.naming import bucket_name

        s3 = self._session.client("s3", region_name=self._region)
        resp = s3.get_object(
            Bucket=bucket_name(cogent_name),
            Key=key,
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
        lam.invoke(
            FunctionName=f"cogent-{safe_name}-executor",
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
        """Register a cogent in the status table and create its database."""
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

        # 3. Apply schema using the polis session's RDS client
        from cogos.db.migrations import apply_schema_with_client
        rds_client = self._session.client("rds-data", region_name=self._region)
        apply_schema_with_client(
            rds_client, db_info["cluster_arn"], db_info["secret_arn"], db_name
        )
        logger.info("Schema applied to %s", db_name)

    def get_secrets_provider(self):
        return self._secrets

    def destroy_cogent(self, name: str) -> None:
        """Remove cogent from status table."""
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
        from polis.naming import bucket_name
        s3 = self._session.client("s3", region_name=self._region)
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name(cogent_name), "Key": key},
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
