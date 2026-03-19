"""CogOS — operating system for cogents."""

import os


def get_sessions_bucket() -> str:
    """Return the S3 sessions bucket name from env, deriving from COGENT_NAME if needed."""
    bucket = os.environ.get("SESSIONS_BUCKET", "")
    if not bucket:
        cogent = os.environ.get("COGENT_NAME", "")
        if cogent:
            safe = cogent.replace(".", "-")
            bucket = f"cogent-{safe}-cogtainer-sessions"
    return bucket
