@{mnt/boot/pointy/whoami/index.md}
@{mnt/boot/pointy/learnings.md}

# Feedback Processing

Process comments on a Daily Thread Update Google Doc. Classify each comment and act.

## Step 1: Find the most recent report

```python
recent = google_docs.list_files("1CDiEcCsr7M0vyzcYYBIidPBCU9kXymNq", limit=1)
doc_id = recent[0].id if recent and not hasattr(recent, 'error') else None
print(f"Doc: {doc_id}")
```

## Step 2: Fetch and classify comments

```python
comments = google_docs.get_comments(doc_id)
for c in comments:
    has_pointy = "@pointy" in c.content.lower()
    for r in c.replies:
        if "@pointy" in r.get("content", "").lower():
            has_pointy = True
    ctype = "Type 2 (directive)" if has_pointy else "Type 1 (correction)"
    print(f"{ctype}: {c.author} on '{c.quoted_text[:60]}': {c.content[:100]}")
```

## Step 3: Process

**Type 1 (corrections):** Append to learnings file.
```python
current = file.read("mnt/boot/pointy/learnings.md")
file.write("mnt/boot/pointy/learnings.md", current.content + "\n- LEARNING NOTE")
```

**Type 2 (directives):** Edit the relevant instruction file.
```python
instructions = file.read("mnt/boot/pointy/daily-instructions.md")
# Apply the change
file.write("mnt/boot/pointy/daily-instructions.md", updated_content)
```

## Step 4: Optionally resolve comments

```python
google_docs.update_comment(doc_id, comment_id, resolved=True)
```
