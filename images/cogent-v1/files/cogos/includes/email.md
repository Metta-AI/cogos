# Email API

Send and receive emails via AWS SES.

## send(to, subject, body, reply_to?)

```python
email.send(
    to="user@example.com",
    subject="Weekly Report",
    body="Here's what happened this week...",
)

# Reply to a thread
email.send(
    to="user@example.com",
    subject="Re: Weekly Report",
    body="Updated numbers attached.",
    reply_to="<original-message-id>",
)
```

Returns `SendResult` — message_id, to, subject.

## receive(limit?)

```python
emails = email.receive(limit=5)
for e in emails:
    print(f"From: {e.sender}")
    print(f"Subject: {e.subject}")
    print(f"Body: {e.body}")
```

Reads from the event log (`email:received` events). Returns `list[EmailMessage]` — sender, to, subject, body, date, message_id.

## Scoping

```python
# Restrict recipients
ops_email = email.scope(to=["ops@company.com", "team@company.com"])

# Send only (no receive)
send_only = email.scope(ops=["send"])

# Both
scoped = email.scope(to=["user@example.com"], ops=["send"])
```
