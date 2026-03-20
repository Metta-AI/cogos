"""Email sender — outbound email via the CogtainerRuntime."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SesSender:
    """Send email via the CogtainerRuntime.send_email() method.

    Accepts either a runtime (preferred) or falls back to boto3 SES for
    backward compatibility during the transition.
    """

    def __init__(self, from_address: str, region: str = "us-east-1", runtime: Any = None):
        self._from = from_address
        self._region = region
        self._runtime = runtime

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to: str | None = None,
    ) -> dict:
        if self._runtime:
            message_id = self._runtime.send_email(
                source=self._from,
                to=to,
                subject=subject,
                body=body,
                reply_to=reply_to,
            )
            logger.info("Sent email to=%s subject=%r message_id=%s", to, subject, message_id)
            return {"MessageId": message_id}

        # Fallback to boto3 for backward compatibility
        import boto3
        client = boto3.client("ses", region_name=self._region)
        kwargs: dict = {
            "Source": self._from,
            "Destination": {"ToAddresses": [to]},
            "Message": {
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body}},
            },
        }
        if reply_to:
            kwargs["ReplyToAddresses"] = [reply_to]
        response = client.send_email(**kwargs)
        logger.info("Sent email to=%s subject=%r message_id=%s", to, subject, response.get("MessageId"))
        return response
