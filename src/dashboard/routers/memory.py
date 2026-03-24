from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cogos.files.context_engine import ContextEngine
from cogos.files.store import FileStore
from dashboard.db import get_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cogos-memory"])


# ── Response models ───────────────────────────────────────────────


class PromptLayer(BaseModel):
    name: str
    content: str
    priority: int


class RenderedPromptResponse(BaseModel):
    prompt: str
    layers: list[PromptLayer]


# ── Routes ────────────────────────────────────────────────────────


@router.get("/memory/rendered", response_model=RenderedPromptResponse)
def get_rendered_memory(
    name: str,
    process_name: str | None = Query(
        None,
        description="Process name to render prompt for. If omitted, returns all file contents with resolved includes.",
    ),
) -> RenderedPromptResponse:
    """Return the fully rendered system prompt.

    If *process_name* is provided, builds the prompt for that specific
    process (resolving all ``@{file-key}`` references).  Otherwise returns
    all files with their includes resolved.
    """
    repo = get_repo()
    file_store = FileStore(repo)
    ctx = ContextEngine(file_store)

    if process_name:
        process = repo.get_process_by_name(process_name)
        if not process:
            raise HTTPException(status_code=404, detail=f"Process not found: {process_name}")

        full_prompt = ctx.generate_full_prompt(process)
        tree = ctx.resolve_prompt_tree(process)

        layers: list[PromptLayer] = []
        for i, node in enumerate(tree):
            layers.append(
                PromptLayer(
                    name=node["key"],
                    content=node["content"],
                    priority=90 - i,  # highest priority first
                )
            )

        return RenderedPromptResponse(prompt=full_prompt, layers=layers)

    # No process specified — return all files with resolved includes.
    files = file_store.list_files(limit=5000)
    layers = []
    sections: list[str] = []

    for idx, f in enumerate(sorted(files, key=lambda f: f.key)):
        content = file_store.get_content(f.key) or ""
        layers.append(
            PromptLayer(
                name=f.key,
                content=content,
                priority=100 - idx,
            )
        )
        sections.append(f"--- {f.key} ---\n{content}")

    full_text = "\n\n".join(sections)
    return RenderedPromptResponse(prompt=full_text, layers=layers)
