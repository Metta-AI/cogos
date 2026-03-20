"""Runtime factory — create the right runtime from a CogtainerEntry."""

from __future__ import annotations

from cogtainer.config import CogtainerEntry
from cogtainer.llm.provider import create_provider
from cogtainer.runtime.base import CogtainerRuntime


def create_runtime(
    entry: CogtainerEntry, cogtainer_name: str = ""
) -> CogtainerRuntime:
    """Instantiate the appropriate runtime for the given cogtainer config."""
    llm = create_provider(entry.llm, region=entry.region or "us-east-1")

    if entry.type in ("local", "docker"):
        from cogtainer.runtime.local import LocalRuntime

        return LocalRuntime(entry=entry, llm=llm)

    if entry.type == "aws":
        from polis.aws import get_polis_session

        from cogtainer.runtime.aws import AwsRuntime

        session, _ = get_polis_session()
        return AwsRuntime(
            entry=entry, llm=llm, session=session, cogtainer_name=cogtainer_name
        )

    raise ValueError(f"Unknown cogtainer type: {entry.type}")
