"""CoGames scrimmage integration for CogOS.

Wraps the ``cogames scrimmage`` CLI to run multi-agent evaluations and
return structured results that can be consumed by CogOS processes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScrimmageConfig:
    """Configuration for a scrimmage evaluation run."""

    mission: str = "tutorial"
    policy: str = "starter"
    episodes: int = 10
    steps: int | None = None
    seed: int = 42
    cogs: int | None = None
    device: str = "auto"
    save_replay_dir: str | None = None


@dataclass
class ScrimmageResult:
    """Parsed result from a scrimmage evaluation."""

    mission_name: str = ""
    episodes: int = 0
    agent_count: int = 0
    avg_agent_metrics: dict = field(default_factory=dict)
    avg_game_stats: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict) -> ScrimmageResult:
        missions = data.get("missions", [])
        if not missions:
            return cls(raw=data)
        m = missions[0]
        summary = m.get("mission_summary", {})
        policies = summary.get("policy_summaries", [{}])
        p = policies[0] if policies else {}
        return cls(
            mission_name=m.get("mission_name", ""),
            episodes=summary.get("episodes", 0),
            agent_count=p.get("agent_count", 0),
            avg_agent_metrics=p.get("avg_agent_metrics", {}),
            avg_game_stats=summary.get("avg_game_stats", {}),
            raw=data,
        )


def _find_cogames_bin() -> str:
    """Locate the cogames executable."""
    path = shutil.which("cogames")
    if path:
        return path
    raise FileNotFoundError(
        "cogames CLI not found. Install it with: uv tool install cogames --python python3.12"
    )


def run_scrimmage(config: ScrimmageConfig | None = None) -> ScrimmageResult:
    """Run a cogames scrimmage evaluation and return parsed results.

    Args:
        config: Scrimmage configuration. Uses defaults if not provided.

    Returns:
        Parsed scrimmage results.

    Raises:
        FileNotFoundError: If cogames CLI is not installed.
        subprocess.CalledProcessError: If the scrimmage command fails.
    """
    if config is None:
        config = ScrimmageConfig()

    cogames = _find_cogames_bin()
    cmd = [
        cogames, "scrimmage",
        "-m", config.mission,
        "-p", config.policy,
        "-e", str(config.episodes),
        "--seed", str(config.seed),
        "--device", config.device,
        "--format", "json",
    ]

    if config.steps is not None:
        cmd.extend(["-s", str(config.steps)])
    if config.cogs is not None:
        cmd.extend(["-c", str(config.cogs)])
    if config.save_replay_dir is not None:
        cmd.extend(["--save-replay-dir", config.save_replay_dir])

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    # cogames outputs progress to stderr, JSON to stdout
    raw = json.loads(result.stdout)
    return ScrimmageResult.from_json(raw)


def list_missions() -> str:
    """List available cogames missions."""
    cogames = _find_cogames_bin()
    result = subprocess.run([cogames, "missions"], capture_output=True, text=True, check=True)
    return result.stdout


def list_policies() -> str:
    """List available cogames policies."""
    cogames = _find_cogames_bin()
    result = subprocess.run([cogames, "policies"], capture_output=True, text=True, check=True)
    return result.stdout
