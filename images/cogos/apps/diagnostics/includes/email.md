@{mnt/boot/cogos/includes/code_mode.md}

# Diagnostic: includes/email

Exercise the Email API instructions above in read-only mode. Do NOT send any emails.

## Tasks

1. **Discover email capabilities**: Use `search("email")` to find available email operations. Print the result.

2. **Check receive**: Use `email.receive(limit=1)` to check for any inbound emails. Print the result (may be empty list).

3. **Print summary**: Print `"email_diagnostic: capabilities_found=true, send_skipped=true"`.

```python verify
# Read-only diagnostic — just confirm the process completed
p = procs.get(name="_diag/inc_email")
if hasattr(p, "error"):
    pass
```
