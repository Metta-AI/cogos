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
    process_name: str = Query(
        ...,
        description="Process name to render prompt for.",
    ),
) -> RenderedPromptResponse:
    """Return the fully rendered system prompt for a process."""
    repo = get_repo()
    file_store = FileStore(repo)
    ctx = ContextEngine(file_store)

    process = repo.get_process_by_name(process_name)
    if not process:
        raise HTTPException(status_code=404, detail=f"Process not found: {process_name}")

    try:
        full_prompt = ctx.generate_full_prompt(process)
        tree = ctx.resolve_prompt_tree(process)
    except Exception as exc:
        logger.exception("Failed to render prompt for process %s", process_name)
        raise HTTPException(status_code=500, detail=f"Failed to render prompt for {process_name}") from exc

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
