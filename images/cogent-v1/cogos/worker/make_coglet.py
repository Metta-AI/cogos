"""Factory for creating worker coglets from a task description."""

from pathlib import Path

from cogos.cog.cog import CogConfig
from cogos.cog.runtime import CogletManifest


def make_coglet(reason: str, cog_dir: Path = None):
    """Create a worker coglet for the given task.

    Returns (CogletManifest, required_capabilities).
    """
    # Read the worker template and cog config
    template = ""
    cog_config = CogConfig(mode="one_shot")
    if cog_dir is not None:
        template_path = cog_dir / "main.md"
        if template_path.exists():
            template = template_path.read_text()
        # Load parent cog config to inherit emoji
        from cogos.cog.cog import _load_config
        parent_config = _load_config(cog_dir)
        cog_config = CogConfig(mode="one_shot", emoji=parent_config.emoji)

    content = template + "\n\n## Task\n\n" + reason

    manifest = CogletManifest(
        name="worker-task",
        config=cog_config,
        content=content,
        entrypoint="main.md",
    )

    # Pick capabilities based on task content
    caps = ["discord", "channels", "stdlib"]

    reason_lower = reason.lower()
    cap_keywords = {
        "github": ["github"],
        "issue": ["github"],
        "pull request": ["github"],
        "pr ": ["github"],
        "email": ["email"],
        "send mail": ["email"],
        "search": ["web_search"],
        "look up": ["web_search"],
        "find out": ["web_search"],
        "fetch": ["web_fetch"],
        "url": ["web_fetch"],
        "http": ["web_fetch"],
        "website": ["web", "web_fetch"],
        "publish": ["web"],
        "image": ["image", "blob"],
        "picture": ["image", "blob"],
        "photo": ["image", "blob"],
        "asana": ["asana"],
        "task": ["asana"],
        "file": ["dir", "file"],
        "read": ["dir", "file"],
        "write": ["dir", "file"],
        "edit": ["dir", "file"],
    }

    for keyword, cap_list in cap_keywords.items():
        if keyword in reason_lower:
            caps.extend(cap_list)

    return manifest, list(set(caps))
