@{mnt/boot/pointy/whoami/index.md}

# Pitch Follow-Up

Check Asana for responses to Pointy's pitch reviews and reply.

## Step 1: Find threads with Pointy reviews

Fetch threads from the current month's section, check comments for
"Pitch Review (Pointy)" followed by replies from others.

```python
project_id = "1213471594342425"
sections = asana.list_sections(project_id)
# Find current month section, fetch tasks, check stories
```

## Step 2: Assess each response

| Situation | Response approach |
|-----------|-------------------|
| Pitch updated | Re-evaluate against What/So What/Now What |
| Owner asks question | Answer directly with example |
| Owner pushes back | Consider their point, respond constructively |
| Owner agrees | Brief acknowledgment, gentle nudge if not updated |

## Step 3: Post follow-ups

Write in Pointy's voice. Prefix with "Pitch Follow-Up (Pointy)".

```python
asana.add_comment(task_id, followup_text)
```
