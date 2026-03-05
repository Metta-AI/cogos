# Google Calendar Setup

Calendar uses the same Google service account as Gmail.
See `src/channels/gmail/guide.md` for the full setup.

The service account needs these additional scopes:
- https://www.googleapis.com/auth/calendar
- https://www.googleapis.com/auth/calendar.events

These are already included in the Gmail guide's scope list.
No separate credential is needed — the Calendar channel
reuses the Gmail service account key at runtime.
