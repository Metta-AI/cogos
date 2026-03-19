"""Version manifest for CogOS boot."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

KNOWN_COMPONENTS = frozenset({
    "executor", "dashboard", "dashboard_frontend",
    "discord_bridge", "lambda", "cogos",
})


@dataclass
class VersionManifest:
    epoch: int
    cogent_name: str
    components: dict[str, str]
    booted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_json(self) -> str:
        return json.dumps({
            "epoch": self.epoch,
            "cogent_name": self.cogent_name,
            "booted_at": self.booted_at,
            "components": self.components,
        }, indent=2)

    @classmethod
    def from_json(cls, text: str) -> VersionManifest:
        data = json.loads(text)
        return cls(
            epoch=data["epoch"],
            cogent_name=data["cogent_name"],
            components=data["components"],
            booted_at=data.get("booted_at", ""),
        )


def resolve_versions(
    defaults: dict[str, str],
    overrides: dict[str, str],
) -> dict[str, str]:
    """Merge defaults with CLI overrides. Raises on unknown components."""
    for key in overrides:
        if key not in KNOWN_COMPONENTS:
            raise ValueError(f"Unknown component: {key}")
    return {**defaults, **overrides}


class ArtifactMissing(Exception):
    pass

_ECR_COMPONENTS = {
    "executor": "executor-{sha}",
    "dashboard": "dashboard-{sha}",
    "discord_bridge": "discord-bridge-{sha}",
}

_S3_COMPONENTS = {
    "lambda": "lambda/{sha}/lambda.zip",
    "dashboard_frontend": "dashboard/{sha}/frontend.tar.gz",
}

_SKIP_VERIFY = {"cogos"}


def verify_artifacts(
    components: dict[str, str],
    *,
    ecr_client,
    s3_client,
    artifacts_bucket: str,
    ecr_repo: str = "cogent",
) -> None:
    for name, sha in components.items():
        if sha == "local" or name in _SKIP_VERIFY:
            continue
        if name in _ECR_COMPONENTS:
            tag = _ECR_COMPONENTS[name].format(sha=sha)
            try:
                ecr_client.describe_images(repositoryName=ecr_repo, imageIds=[{"imageTag": tag}])
            except Exception:
                raise ArtifactMissing(f"{name}: ECR image '{ecr_repo}:{tag}' not found")
        if name in _S3_COMPONENTS:
            key = _S3_COMPONENTS[name].format(sha=sha)
            try:
                s3_client.head_object(Bucket=artifacts_bucket, Key=key)
            except Exception:
                raise ArtifactMissing(f"{name}: S3 artifact 's3://{artifacts_bucket}/{key}' not found")


def load_defaults(image_dir: Path) -> dict[str, str]:
    defaults_file = image_dir / "versions.defaults.json"
    if defaults_file.exists():
        return json.loads(defaults_file.read_text())
    return {c: "local" for c in KNOWN_COMPONENTS}


def write_versions_to_filestore(manifest: VersionManifest, fs) -> None:
    fs.upsert("mnt/boot/versions.json", manifest.to_json(), source="boot")
