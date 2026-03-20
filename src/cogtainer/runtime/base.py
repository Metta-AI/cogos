"""CogtainerRuntime — abstract interface for cogent lifecycle and I/O."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CogtainerRuntime(ABC):
    """Abstract base for cogtainer runtimes (local, AWS, Docker, etc.)."""

    @abstractmethod
    def get_repository(self, cogent_name: str) -> Any:
        """Return a database repository for the given cogent."""

    @abstractmethod
    def converse(
        self,
        *,
        messages: list[dict],
        system: list[dict],
        tool_config: dict,
        model: str | None = None,
    ) -> dict:
        """Call the LLM and return a Bedrock-format response."""

    @abstractmethod
    def put_file(self, cogent_name: str, key: str, data: bytes) -> str:
        """Store a blob and return the storage key."""

    @abstractmethod
    def get_file(self, cogent_name: str, key: str) -> bytes:
        """Retrieve a blob by key."""

    @abstractmethod
    def emit_event(self, cogent_name: str, event: dict) -> None:
        """Route an event from the given cogent."""

    @abstractmethod
    def spawn_executor(self, cogent_name: str, process_id: str) -> None:
        """Launch an executor for the given process."""

    @abstractmethod
    def list_cogents(self) -> list[str]:
        """Return names of all cogents managed by this cogtainer."""

    @abstractmethod
    def create_cogent(self, name: str) -> None:
        """Provision a new cogent."""

    @abstractmethod
    def get_secrets_provider(self) -> Any:
        """Return the SecretsProvider for this runtime."""

    @abstractmethod
    def destroy_cogent(self, name: str) -> None:
        """Remove a cogent and all its data."""

    @abstractmethod
    def send_queue_message(self, queue_name: str, body: str, *, dedup_id: str | None = None) -> None:
        """Send a message to a named queue."""

    @abstractmethod
    def get_queue_url(self, queue_name: str) -> str:
        """Return the URL for a named queue."""

    @abstractmethod
    def get_file_url(self, cogent_name: str, key: str, expires_in: int = 604800) -> str:
        """Return a URL for a stored blob."""

    @abstractmethod
    def send_email(self, *, source: str, to: str, subject: str, body: str, reply_to: str | None = None) -> str:
        """Send an email. Returns message ID."""

    @abstractmethod
    def verify_email_domain(self, domain: str) -> bool:
        """Check if a domain is verified for sending."""

    @abstractmethod
    def get_bedrock_client(self) -> Any:
        """Return a Bedrock runtime client, or None if not applicable."""

    @abstractmethod
    def get_session(self) -> Any:
        """Return the underlying cloud session (e.g. boto3.Session), or None."""

    @abstractmethod
    def get_dynamodb_resource(self, region: str | None = None) -> Any:
        """Return a DynamoDB resource, or None if not applicable."""

    @abstractmethod
    def get_sqs_client(self, region: str | None = None) -> Any:
        """Return an SQS client, or None if not applicable."""

    @abstractmethod
    def get_s3_client(self, region: str | None = None) -> Any:
        """Return an S3 client, or None if not applicable."""

    @abstractmethod
    def get_ecs_client(self, region: str | None = None) -> Any:
        """Return an ECS client, or None if not applicable."""

    @abstractmethod
    def get_rds_data_client(self, region: str | None = None) -> Any:
        """Return an RDS Data API client, or None if not applicable."""
