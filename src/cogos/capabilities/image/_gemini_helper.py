"""Shared Gemini client initialization for image AI capabilities."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_gemini_client():
    """Return a configured google.genai.Client using the cogent's Gemini API key.

    Checks GOOGLE_API_KEY env var first (for local dev), then falls back
    to fetching from cogent/{cogent}/gemini via secrets manager.
    """
    import os

    from google import genai

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        from cogos.capabilities._secrets_helper import fetch_secret

        api_key = fetch_secret("cogent/{cogent}/gemini", field="api_key")
    return genai.Client(api_key=api_key)
