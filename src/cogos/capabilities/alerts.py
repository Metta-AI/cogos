"""Alerts capability — emit warnings and errors to the algedonic channel."""
from __future__ import annotations

from pydantic import BaseModel

from cogos.capabilities.base import Capability


class AlertResult(BaseModel):
    id: str
    severity: str
    alert_type: str


class AlertError(BaseModel):
    error: str


class AlertsCapability(Capability):
    """Emit system alerts (warnings, errors) visible in the dashboard.

    Usage:
        alerts.warning("scheduler:stuck", "Process X was stuck, recovered")
        alerts.error("executor:crash", "Run failed with OOM")
    """

    def warning(self, alert_type: str, message: str, **metadata) -> AlertResult | AlertError:
        """Emit a warning alert."""
        return self._emit("warning", alert_type, message, metadata)

    def error(self, alert_type: str, message: str, **metadata) -> AlertResult | AlertError:
        """Emit a critical-severity alert."""
        return self._emit("critical", alert_type, message, metadata)

    def _emit(self, severity: str, alert_type: str, message: str, metadata: dict) -> AlertResult | AlertError:
        proc = self.repo.get_process(self.process_id)
        source = proc.name if proc else str(self.process_id)
        try:
            self.repo.create_alert(
                severity=severity,
                alert_type=alert_type,
                source=source,
                message=message,
                metadata=metadata,
            )
            return AlertResult(id="ok", severity=severity, alert_type=alert_type)
        except Exception as e:
            return AlertError(error=str(e))
