# Google Integration Design

## Overview

Add Google Drive, Docs, Sheets, and Calendar integration to cogents using GCP service accounts. Each cogent gets its own service account at creation time. `softmax.com` Workspace users share files/calendars with the service account email, just like sharing with any external collaborator.

## Requirements

- Provisioned automatically during `cogent create` — zero human interaction
- No Google Workspace seats needed — uses free GCP service accounts
- Cogents access Google resources shared with their service account email
- Scoped sub-capabilities: `google.drive`, `google.docs`, `google.sheets`, `google.calendar`

## Service Account Provisioning

During `cogent create`:

1. Call GCP IAM API to create service account: `{cogent_name}@cogents-project.iam.gserviceaccount.com`
2. Generate a JSON key
3. Store JSON key in Secrets Manager at `cogent/{name}/google`
4. Service account email stored in cogent config for dashboard display

During `cogent delete`:

1. Delete the GCP service account (revokes all access, removes from shared resources)
2. Delete the secret from Secrets Manager

APIs (Drive, Docs, Sheets, Calendar) assumed already enabled on the `cogents` GCP project.

## Integration Class

`GoogleIntegration` in `src/cogos/io/google/integration.py`:

- **Fields:** Service account email (read-only, informational), scope toggles (drive, docs, sheets, calendar)
- **Config:** Loaded from `cogent/{name}/google` — contains service account JSON key
- **Status:** Verifies service account key exists and is valid
- **No OAuth flow** — service account keys authenticate directly

Dashboard setup page shows: "Share files/calendars with `{sa_email}`" and scope toggles.

## Google Capability

One `google` capability with four sub-capabilities, each independently enableable:

### `google.drive`

- `search(query)` — search files shared with the cogent
- `list(folder_id?)` — list folder contents
- `get(file_id)` — get file metadata
- `download(file_id)` — download file content
- `upload(name, content, folder_id?, mime_type?)` — create/upload a file
- `share(file_id, email, role)` — share with someone

### `google.docs`

- `create(title, content?)` — create a new doc
- `read(doc_id)` — read doc content as plain text/markdown
- `update(doc_id, content)` — replace doc content

### `google.sheets`

- `create(title)` — create a spreadsheet
- `read(sheet_id, range)` — read cell range
- `write(sheet_id, range, values)` — write cell range

### `google.calendar`

- `list_events(start, end, calendar_id?)` — list events in range
- `create_event(title, start, end, attendees?, description?)` — create event
- `update_event(event_id, ...)` — update event
- `delete_event(event_id)` — delete event

MCP tools exposed as `cogos_google_drive_search`, `cogos_google_calendar_list_events`, etc.

## Auth Pattern

Service account JSON loaded from Secrets Manager, credentials scoped to relevant API, service client built and cached in-memory per capability instance.

## Dependencies

- `google-api-python-client` — Drive, Sheets, Calendar APIs
- `google-auth` — service account credential loading

## File Structure

```
src/cogos/io/google/
  __init__.py
  integration.py      # GoogleIntegration class
  auth.py             # service account credential loading + caching
  capability.py       # registers google.drive, google.docs, etc.
  drive.py            # drive sub-capability methods
  docs.py             # docs sub-capability methods
  sheets.py           # sheets sub-capability methods
  calendar.py         # calendar sub-capability methods
```

## Provisioning Changes

- `cogent create` — add GCP service account creation after DB setup
- `cogent delete` — add GCP service account deletion
- `images/cogos/init/capabilities.py` — register `google.*` in `BUILTIN_CAPABILITIES`

## Error Handling

- **Permission errors:** Google API returns 404 for unshared files. Return clear message with service account email to share with.
- **Rate limits:** Each service account counts as its own user. Generous per-user quotas, no special handling needed.
- **Key rotation:** Not built now. Single-secret pattern makes it straightforward later (create new key, store, delete old).
- **Local cogtainers:** Get real GCP service accounts (shared GCP project), same as Asana/Discord.
