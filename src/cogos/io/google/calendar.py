"""Google Calendar capability — list, create, update, and delete events."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.io.google.auth import get_service

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class EventInfo(BaseModel):
    id: str
    title: str
    start: str
    end: str
    description: str = ""
    attendees: list[str] = []
    calendar_id: str = ""
    url: str = ""


class EventResult(BaseModel):
    id: str
    title: str
    url: str = ""


class DeleteResult(BaseModel):
    event_id: str
    deleted: bool


class CalendarError(BaseModel):
    error: str


# ── Helpers ──────────────────────────────────────────────────


def _event_info(event: dict[str, Any], calendar_id: str = "primary") -> EventInfo:
    return EventInfo(
        id=event["id"],
        title=event.get("summary", ""),
        start=event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", ""),
        end=event.get("end", {}).get("dateTime") or event.get("end", {}).get("date", ""),
        description=event.get("description", ""),
        attendees=[a["email"] for a in event.get("attendees", [])],
        calendar_id=calendar_id,
        url=event.get("htmlLink", ""),
    )


# ── Capability ───────────────────────────────────────────────


class CalendarCapability(Capability):
    """List, create, update, and delete Google Calendar events.

    The cogent's service account must have access to the target calendar
    (e.g. the calendar is shared with the service account email).
    """

    ALL_OPS = {"list_events", "create_event", "update_event", "delete_event"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict = {}
        for key in ("ops",):
            old, new = existing.get(key), requested.get(key)
            if old is not None and new is not None:
                result[key] = set(old) & set(new)
            elif old is not None:
                result[key] = old
            elif new is not None:
                result[key] = new
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(
                f"CalendarCapability: '{op}' not allowed (allowed: {allowed_ops})"
            )

    def _calendar(self) -> Any:
        return get_service("calendar", "v3", self._secrets_provider)

    # ── Public methods ───────────────────────────────────────

    def list_events(
        self,
        start: str,
        end: str,
        calendar_id: str = "primary",
        limit: int = 50,
    ) -> list[EventInfo] | CalendarError:
        """List events between start and end (ISO 8601 datetime strings)."""
        self._check("list_events")
        try:
            resp = (
                self._calendar()
                .events()
                .list(
                    calendarId=calendar_id,
                    timeMin=start,
                    timeMax=end,
                    maxResults=limit,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            return [_event_info(e, calendar_id) for e in resp.get("items", [])]
        except Exception as exc:
            logger.exception("Calendar list_events failed")
            return CalendarError(error=str(exc))

    def create_event(
        self,
        title: str,
        start: str,
        end: str,
        attendees: list[str] | None = None,
        description: str = "",
        calendar_id: str = "primary",
    ) -> EventResult | CalendarError:
        """Create a new calendar event."""
        self._check("create_event")
        try:
            body: dict[str, Any] = {
                "summary": title,
                "start": {"dateTime": start},
                "end": {"dateTime": end},
                "description": description,
            }
            if attendees:
                body["attendees"] = [{"email": e} for e in attendees]

            event = (
                self._calendar()
                .events()
                .insert(calendarId=calendar_id, body=body)
                .execute()
            )
            return EventResult(
                id=event["id"],
                title=event.get("summary", title),
                url=event.get("htmlLink", ""),
            )
        except Exception as exc:
            logger.exception("Calendar create_event failed")
            return CalendarError(error=str(exc))

    def update_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
        **fields: Any,
    ) -> EventResult | CalendarError:
        """Update an existing event. Supported fields: title, start, end, description, attendees."""
        self._check("update_event")
        try:
            body: dict[str, Any] = {}
            if "title" in fields:
                body["summary"] = fields["title"]
            if "start" in fields:
                body["start"] = {"dateTime": fields["start"]}
            if "end" in fields:
                body["end"] = {"dateTime": fields["end"]}
            if "description" in fields:
                body["description"] = fields["description"]
            if "attendees" in fields:
                body["attendees"] = [{"email": e} for e in fields["attendees"]]

            event = (
                self._calendar()
                .events()
                .patch(calendarId=calendar_id, eventId=event_id, body=body)
                .execute()
            )
            return EventResult(
                id=event["id"],
                title=event.get("summary", ""),
                url=event.get("htmlLink", ""),
            )
        except Exception as exc:
            logger.exception("Calendar update_event failed")
            return CalendarError(error=str(exc))

    def delete_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
    ) -> DeleteResult | CalendarError:
        """Delete a calendar event."""
        self._check("delete_event")
        try:
            self._calendar().events().delete(
                calendarId=calendar_id, eventId=event_id
            ).execute()
            return DeleteResult(event_id=event_id, deleted=True)
        except Exception as exc:
            logger.exception("Calendar delete_event failed")
            return CalendarError(error=str(exc))

    def __repr__(self) -> str:
        return "<CalendarCapability list_events() create_event() update_event() delete_event()>"
