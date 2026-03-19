# Versioned Boot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Boot CogOS with an explicit map of versioned components, verified to exist before proceeding.

**Architecture:** A `versions.defaults.json` in the image spec provides baseline component SHAs. `cogos image boot` resolves versions (defaults + CLI overrides), verifies artifacts exist in ECR/S3, writes `/mnt/boot/versions.json`, then continues the existing boot sequence. CI auto-updates `versions.defaults.json` on main after building artifacts.

**Tech Stack:** Python, boto3 (ECR/S3), Click CLI, GitHub Actions YAML

---

### Task 1: Version Manifest Model

**Files:**
- Create: `src/cogos/image/versions.py`
- Test: `tests/cogos/image/test_versions.py`

**Step 1: Write the test**

```python
# tests/cogos/image/test_versions.py
"""Tests for version manifest model and resolution."""
import json
import pytest
from cogos.image.versions import VersionManifest, resolve_versions


def test_manifest_roundtrip():
    m = VersionManifest(
        epoch=3,
        cogent_name="dr.alpha",
        components={
            "executor": "abc1234",
            "dashboard": "def5678",
            "dashboard_frontend": "ghi9012",
            "discord_bridge": "pqr2345",
            "lambda": "jkl3456",
            "cogos": "mno7890",
        },
    )
    data = json.loads(m.to_json())
    assert data["epoch"] == 3
    assert data["cogent_name"] == "dr.alpha"
    assert data["components"]["executor"] == "abc1234"
    assert "booted_at" in data

    m2 = VersionManifest.from_json(m.to_json())
    assert m2.epoch == m.epoch
    assert m2.components == m.components


def test_resolve_defaults_only():
    defaults = {"executor": "aaa", "dashboard": "bbb", "lambda": "ccc", "cogos": "ddd",
                "dashboard_frontend": "eee", "discord_bridge": "fff"}
    result = resolve_versions(defaults, overrides={})
    assert result == defaults


def test_resolve_with_overrides():
    defaults = {"executor": "aaa", "dashboard": "bbb", "lambda": "ccc", "cogos": "ddd",
                "dashboard_frontend": "eee", "discord_bridge": "fff"}
    result = resolve_versions(defaults, overrides={"executor": "zzz"})
    assert result["executor"] == "zzz"
    assert result["dashboard"] == "bbb"


def test_resolve_rejects_unknown_component():
    defaults = {"executor": "aaa"}
    with pytest.raises(ValueError, match="Unknown component"):
        resolve_versions(defaults, overrides={"bogus": "zzz"})
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.1 && python -m pytest tests/cogos/image/test_versions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cogos.image.versions'`

**Step 3: Write implementation**

```python
# src/cogos/image/versions.py
"""Version manifest for CogOS boot."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

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
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.1 && python -m pytest tests/cogos/image/test_versions.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/image/versions.py tests/cogos/image/test_versions.py
git commit -m "feat(versions): add VersionManifest model and resolve_versions"
```

---

### Task 2: Artifact Verification

**Files:**
- Modify: `src/cogos/image/versions.py`
- Test: `tests/cogos/image/test_versions.py`

**Step 1: Write the test**

Append to `tests/cogos/image/test_versions.py`:

```python
from unittest.mock import MagicMock
from cogos.image.versions import verify_artifacts, ArtifactMissing


def test_verify_all_present(tmp_path):
    """Verify passes when all artifacts exist."""
    components = {"executor": "abc", "dashboard": "def", "dashboard_frontend": "ghi",
                  "discord_bridge": "pqr", "lambda": "jkl", "cogos": "mno"}

    ecr = MagicMock()
    ecr.describe_images = MagicMock(return_value={})
    s3 = MagicMock()
    s3.head_object = MagicMock(return_value={})

    # Should not raise
    verify_artifacts(components, ecr_client=ecr, s3_client=s3, artifacts_bucket="test-bucket")


def test_verify_ecr_missing():
    """Verify raises when ECR image is missing."""
    components = {"executor": "abc", "dashboard": "def", "dashboard_frontend": "ghi",
                  "discord_bridge": "pqr", "lambda": "jkl", "cogos": "mno"}

    ecr = MagicMock()
    ecr.describe_images = MagicMock(side_effect=Exception("not found"))
    s3 = MagicMock()
    s3.head_object = MagicMock(return_value={})

    with pytest.raises(ArtifactMissing, match="executor"):
        verify_artifacts(components, ecr_client=ecr, s3_client=s3, artifacts_bucket="test-bucket")


def test_verify_s3_missing():
    """Verify raises when S3 artifact is missing."""
    components = {"executor": "abc", "dashboard": "def", "dashboard_frontend": "ghi",
                  "discord_bridge": "pqr", "lambda": "jkl", "cogos": "mno"}

    ecr = MagicMock()
    ecr.describe_images = MagicMock(return_value={})
    s3 = MagicMock()
    s3.head_object = MagicMock(side_effect=Exception("not found"))

    with pytest.raises(ArtifactMissing, match="lambda"):
        verify_artifacts(components, ecr_client=ecr, s3_client=s3, artifacts_bucket="test-bucket")


def test_verify_skipped_for_local():
    """Verify skips checks when version is 'local'."""
    components = {"executor": "local", "dashboard": "local", "dashboard_frontend": "local",
                  "discord_bridge": "local", "lambda": "local", "cogos": "local"}
    # Should not raise even with no clients
    verify_artifacts(components, ecr_client=None, s3_client=None, artifacts_bucket="test-bucket")
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.1 && python -m pytest tests/cogos/image/test_versions.py::test_verify_all_present -v`
Expected: FAIL — `ImportError: cannot import name 'verify_artifacts'`

**Step 3: Write implementation**

Add to `src/cogos/image/versions.py`:

```python
class ArtifactMissing(Exception):
    """Raised when a required artifact is not found."""
    pass


# Map component name -> artifact type and location pattern
_ECR_COMPONENTS = {
    "executor": "executor-{sha}",
    "dashboard": "dashboard-{sha}",
    "discord_bridge": "discord-bridge-{sha}",
}

_S3_COMPONENTS = {
    "lambda": "lambda/{sha}/lambda.zip",
    "dashboard_frontend": "dashboard/{sha}/frontend.tar.gz",
}

# cogos is a git ref, no artifact to verify
_SKIP_VERIFY = {"cogos"}


def verify_artifacts(
    components: dict[str, str],
    *,
    ecr_client,
    s3_client,
    artifacts_bucket: str,
    ecr_repo: str = "cogent",
) -> None:
    """Verify all component artifacts exist. Raises ArtifactMissing on first failure."""
    for name, sha in components.items():
        if sha == "local" or name in _SKIP_VERIFY:
            continue

        if name in _ECR_COMPONENTS:
            tag = _ECR_COMPONENTS[name].format(sha=sha)
            try:
                ecr_client.describe_images(
                    repositoryName=ecr_repo,
                    imageIds=[{"imageTag": tag}],
                )
            except Exception:
                raise ArtifactMissing(
                    f"{name}: ECR image '{ecr_repo}:{tag}' not found"
                )

        if name in _S3_COMPONENTS:
            key = _S3_COMPONENTS[name].format(sha=sha)
            try:
                s3_client.head_object(Bucket=artifacts_bucket, Key=key)
            except Exception:
                raise ArtifactMissing(
                    f"{name}: S3 artifact 's3://{artifacts_bucket}/{key}' not found"
                )
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.1 && python -m pytest tests/cogos/image/test_versions.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/image/versions.py tests/cogos/image/test_versions.py
git commit -m "feat(versions): add artifact verification for ECR and S3"
```

---

### Task 3: Defaults File & Load Function

**Files:**
- Create: `images/cogent-v1/versions.defaults.json`
- Modify: `src/cogos/image/versions.py`
- Test: `tests/cogos/image/test_versions.py`

**Step 1: Write the test**

Append to `tests/cogos/image/test_versions.py`:

```python
from pathlib import Path
from cogos.image.versions import load_defaults


def test_load_defaults(tmp_path):
    defaults_file = tmp_path / "versions.defaults.json"
    defaults_file.write_text(json.dumps({
        "executor": "aaa", "dashboard": "bbb", "dashboard_frontend": "ccc",
        "discord_bridge": "ddd", "lambda": "eee", "cogos": "fff",
    }))
    result = load_defaults(tmp_path)
    assert result["executor"] == "aaa"
    assert len(result) == 6


def test_load_defaults_missing(tmp_path):
    """Returns all 'local' when file is missing."""
    result = load_defaults(tmp_path)
    for v in result.values():
        assert v == "local"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.1 && python -m pytest tests/cogos/image/test_versions.py::test_load_defaults -v`
Expected: FAIL

**Step 3: Write implementation**

Add to `src/cogos/image/versions.py`:

```python
from pathlib import Path

def load_defaults(image_dir: Path) -> dict[str, str]:
    """Load version defaults from image directory. Returns 'local' for all if missing."""
    defaults_file = image_dir / "versions.defaults.json"
    if defaults_file.exists():
        return json.loads(defaults_file.read_text())
    return {c: "local" for c in KNOWN_COMPONENTS}
```

Create `images/cogent-v1/versions.defaults.json`:

```json
{
  "executor": "local",
  "dashboard": "local",
  "dashboard_frontend": "local",
  "discord_bridge": "local",
  "lambda": "local",
  "cogos": "local"
}
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.1 && python -m pytest tests/cogos/image/test_versions.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/image/versions.py tests/cogos/image/test_versions.py images/cogent-v1/versions.defaults.json
git commit -m "feat(versions): add defaults file and load_defaults"
```

---

### Task 4: Write versions.json to /mnt/boot/ in apply_image

**Files:**
- Modify: `src/cogos/image/apply.py`
- Modify: `src/cogos/image/versions.py`
- Test: `tests/cogos/image/test_versions.py`

**Step 1: Write the test**

Append to `tests/cogos/image/test_versions.py`:

```python
from cogos.image.versions import write_versions_to_filestore


def test_write_versions_to_filestore():
    """Verify manifest is written to _boot/versions.json via FileStore."""
    from unittest.mock import MagicMock

    manifest = VersionManifest(
        epoch=1,
        cogent_name="test",
        components={"executor": "aaa", "dashboard": "bbb", "dashboard_frontend": "ccc",
                     "discord_bridge": "ddd", "lambda": "eee", "cogos": "fff"},
    )
    fs = MagicMock()
    write_versions_to_filestore(manifest, fs)
    fs.upsert.assert_called_once()
    call_args = fs.upsert.call_args
    assert call_args[0][0] == "mnt/boot/versions.json"
    written = json.loads(call_args[0][1])
    assert written["epoch"] == 1
    assert written["components"]["executor"] == "aaa"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.1 && python -m pytest tests/cogos/image/test_versions.py::test_write_versions_to_filestore -v`
Expected: FAIL

**Step 3: Write implementation**

Add to `src/cogos/image/versions.py`:

```python
def write_versions_to_filestore(manifest: VersionManifest, fs) -> None:
    """Write version manifest to the boot mount via FileStore."""
    fs.upsert("mnt/boot/versions.json", manifest.to_json(), source="boot")
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.1 && python -m pytest tests/cogos/image/test_versions.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/image/versions.py tests/cogos/image/test_versions.py
git commit -m "feat(versions): add write_versions_to_filestore"
```

---

### Task 5: Integrate into cogos image boot CLI

**Files:**
- Modify: `src/cogos/cli/__main__.py` (the `boot` command, lines ~156-189)
- Test: manual — run `cogos image boot --dry-run` locally

**Step 1: Add CLI options to boot command**

Modify `src/cogos/cli/__main__.py` boot command (line 156-189). Add version override options and `--dry-run`:

```python
@image.command()
@click.argument("name", default="cogent-v1")
@click.option("--clean", is_flag=True, help="Wipe all tables before loading")
@click.option("--dry-run", is_flag=True, help="Resolve and verify versions, then exit")
@click.option("--executor", "v_executor", default=None, help="Override executor version SHA")
@click.option("--dashboard", "v_dashboard", default=None, help="Override dashboard version SHA")
@click.option("--dashboard-frontend", "v_dashboard_frontend", default=None, help="Override dashboard frontend SHA")
@click.option("--discord-bridge", "v_discord_bridge", default=None, help="Override discord bridge SHA")
@click.option("--lambda", "v_lambda", default=None, help="Override lambda version SHA")
@click.option("--cogos-version", "v_cogos", default=None, help="Override cogos version SHA")
@click.pass_context
def boot(ctx, name, clean, dry_run, v_executor, v_dashboard, v_dashboard_frontend,
         v_discord_bridge, v_lambda, v_cogos):
    """Boot CogOS from an image (default: cogent-v1)."""
    from cogos.image.apply import apply_image
    from cogos.image.spec import load_image
    from cogos.image.versions import (
        VersionManifest, load_defaults, resolve_versions,
        verify_artifacts, write_versions_to_filestore, ArtifactMissing,
    )
    from cogos.files.store import FileStore

    repo_root = Path(__file__).resolve().parents[3]
    image_dir = repo_root / "images" / name
    if not image_dir.is_dir():
        click.echo(f"Image not found: {image_dir}")
        return

    # 1. Resolve versions
    defaults = load_defaults(image_dir)
    overrides = {}
    for key, val in [("executor", v_executor), ("dashboard", v_dashboard),
                     ("dashboard_frontend", v_dashboard_frontend),
                     ("discord_bridge", v_discord_bridge),
                     ("lambda", v_lambda), ("cogos", v_cogos)]:
        if val is not None:
            overrides[key] = val

    components = resolve_versions(defaults, overrides)
    click.echo("Resolved versions:")
    for k, v in sorted(components.items()):
        click.echo(f"  {k}: {v}")

    # 2. Verify artifacts (skip for local dev)
    is_local = all(v == "local" for v in components.values())
    if not is_local:
        click.echo("Verifying artifacts...")
        try:
            import boto3
            session = boto3.Session()
            verify_artifacts(
                components,
                ecr_client=session.client("ecr", region_name="us-east-1"),
                s3_client=session.client("s3"),
                artifacts_bucket="cogent-polis-ci-artifacts",
            )
            click.echo("All artifacts verified.")
        except ArtifactMissing as e:
            click.echo(f"ERROR: {e}")
            return

    if dry_run:
        click.echo("Dry run complete.")
        return

    repo = _repo()
    _run_migrations(repo)

    if clean:
        repo.clear_all()
        repo.set_meta("reboot_epoch", "0")
        click.echo("Tables cleaned.")

    # 3. Get epoch from DB
    epoch = repo.reboot_epoch

    # 4. Write versions manifest
    cogent_name = os.environ.get("COGENT_NAME", name)
    manifest = VersionManifest(epoch=epoch, cogent_name=cogent_name, components=components)
    fs = FileStore(repo)
    write_versions_to_filestore(manifest, fs)
    click.echo(f"Wrote versions.json (epoch={epoch})")

    # 5. Continue normal boot
    spec = load_image(image_dir)
    counts = apply_image(spec, repo)

    click.echo(
        f"Boot complete: {counts['capabilities']} capabilities, "
        f"{counts['resources']} resources, {counts['files']} files, "
        f"{counts['processes']} processes, {counts['cron']} cron"
    )
```

Note: add `import os` at top of file if not already there.

**Step 2: Run test to verify boot still works locally**

Run: `cd /Users/daveey/code/cogents/cogents.1 && python -m pytest tests/cogos/image/ -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/cogos/cli/__main__.py
git commit -m "feat(boot): integrate version resolution and verification into cogos image boot"
```

---

### Task 6: Orchestrator reads executor version from manifest

**Files:**
- Modify: `src/cogtainer/lambdas/orchestrator/handler.py`

**Step 1: Add version-aware image override to _dispatch_ecs**

In `src/cogtainer/lambdas/orchestrator/handler.py`, modify `_dispatch_ecs` to accept an optional `image_override` parameter and read it from the config/versions:

```python
def _dispatch_ecs(config, ecs_client, payload: str, program_name: str,
                  session_id: str | None = None):
    """Run executor as ECS Fargate task for heavy compute."""
    subnets = [s.strip() for s in config.ecs_subnets.split(",") if s.strip()]

    env_vars = [{"name": "EXECUTOR_PAYLOAD", "value": payload}]
    if session_id:
        env_vars.append({"name": "CLAUDE_CODE_SESSION", "value": session_id})

    container_overrides = {
        "name": "Executor",
        "environment": env_vars,
    }

    # Apply executor version image override if configured
    if config.executor_image_override:
        container_overrides["image"] = config.executor_image_override

    ecs_client.run_task(
        cluster=config.ecs_cluster_arn,
        taskDefinition=config.ecs_task_definition,
        launchType="FARGATE",
        enableExecuteCommand=True,
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": subnets,
                "securityGroups": [config.ecs_security_group],
                "assignPublicIp": "ENABLED",
            }
        },
        overrides={
            "containerOverrides": [container_overrides]
        },
    )
    logger.info(f"Dispatched to ECS: {program_name} (session={session_id})")
```

This requires adding `executor_image_override` to the config model. Check `src/cogtainer/lambdas/shared/config.py` and add:

```python
executor_image_override: str | None = None  # Set from versions.json at boot
```

The boot process should set the `EXECUTOR_IMAGE_OVERRIDE` env var on the Lambda functions when updating them, constructed from `{ecr_repo_uri}:executor-{sha}`.

**Step 2: Run existing orchestrator tests**

Run: `cd /Users/daveey/code/cogents/cogents.1 && python -m pytest tests/cogtainer/ -v -k orchestrator`
Expected: PASS

**Step 3: Commit**

```bash
git add src/cogtainer/lambdas/orchestrator/handler.py src/cogtainer/lambdas/shared/config.py
git commit -m "feat(orchestrator): support executor image override from version config"
```

---

### Task 7: CLI update commands read from versions manifest

**Files:**
- Modify: `src/cogtainer/update_cli.py`

**Step 1: Add helper to read versions from boot manifest**

Add to `src/cogtainer/update_cli.py`:

```python
def _read_boot_versions(session: boto3.Session, safe_name: str) -> dict[str, str] | None:
    """Read versions.json from the cogent's database via FileStore."""
    try:
        _ensure_db_env(safe_name.replace("-", "."))
        from cogos.db.repository import Repository
        from cogos.files.store import FileStore
        repo = Repository.create()
        fs = FileStore(repo)
        content = fs.get_content("mnt/boot/versions.json")
        if content:
            import json
            return json.loads(content).get("components", {})
    except Exception:
        pass
    return None
```

**Step 2: Modify update_lambda to optionally use versions manifest**

Update `update_lambda` to check boot versions when no `--sha` is provided. If a version is set and not "local", use it:

In the `update_lambda` function, after checking for `--sha`, add a fallback to boot versions:

```python
    if not sha:
        versions = _read_boot_versions(session, safe_name)
        if versions and versions.get("lambda") and versions["lambda"] != "local":
            sha = versions["lambda"]
            click.echo(f"  Using lambda version from boot manifest: {sha[:8]}")
```

**Step 3: Modify update_ecs to optionally use versions manifest**

Similar pattern for `update_ecs` — if no `--tag` is provided, look up dashboard version from manifest.

**Step 4: Run existing CLI tests**

Run: `cd /Users/daveey/code/cogents/cogents.1 && python -m pytest tests/cogtainer/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogtainer/update_cli.py
git commit -m "feat(cli): update commands read versions from boot manifest"
```

---

### Task 8: CI auto-updates versions.defaults.json

**Files:**
- Create: `.github/actions/update-versions/action.yml`
- Modify: `.github/workflows/docker-build-executor.yml`
- Modify: `.github/workflows/docker-build-dashboard.yml`

**Step 1: Create reusable action**

```yaml
# .github/actions/update-versions/action.yml
name: "Update versions.defaults.json"
description: "Update a component version in versions.defaults.json and commit"

inputs:
  component:
    description: "Component key to update (e.g. executor, dashboard)"
    required: true
  version:
    description: "Version SHA to set"
    required: true
  defaults_file:
    description: "Path to versions.defaults.json"
    required: false
    default: "images/cogent-v1/versions.defaults.json"

runs:
  using: "composite"
  steps:
    - name: Update versions.defaults.json
      shell: bash
      run: |
        FILE="${{ inputs.defaults_file }}"
        COMPONENT="${{ inputs.component }}"
        VERSION="${{ inputs.version }}"

        # Use python to update JSON (preserves formatting)
        python3 -c "
        import json
        with open('$FILE') as f:
            data = json.load(f)
        data['$COMPONENT'] = '$VERSION'
        with open('$FILE', 'w') as f:
            json.dump(data, f, indent=2)
            f.write('\n')
        "
        echo "Updated $COMPONENT to $VERSION in $FILE"

    - name: Commit and push
      shell: bash
      run: |
        git config user.name "github-actions[bot]"
        git config user.email "github-actions[bot]@users.noreply.github.com"
        git add "${{ inputs.defaults_file }}"
        git diff --cached --quiet && echo "No changes" && exit 0
        git commit -m "ci: update ${{ inputs.component }} version to ${{ inputs.version }}"
        git push
```

**Step 2: Add step to executor workflow**

Append to `.github/workflows/docker-build-executor.yml` after the Summary step:

```yaml
      - name: Update versions defaults (executor)
        uses: ./.github/actions/update-versions
        with:
          component: executor
          version: ${{ steps.vars.outputs.short_sha }}

      - name: Update versions defaults (lambda)
        uses: ./.github/actions/update-versions
        with:
          component: lambda
          version: ${{ github.sha }}

      - name: Update versions defaults (cogos)
        uses: ./.github/actions/update-versions
        with:
          component: cogos
          version: ${{ github.sha }}
```

**Step 3: Add step to dashboard workflow**

Append to `.github/workflows/docker-build-dashboard.yml` after the Summary step:

```yaml
      - name: Update versions defaults (dashboard)
        uses: ./.github/actions/update-versions
        with:
          component: dashboard
          version: ${{ steps.vars.outputs.short_sha }}

      - name: Update versions defaults (dashboard_frontend)
        uses: ./.github/actions/update-versions
        with:
          component: dashboard_frontend
          version: ${{ github.sha }}
```

Note: The CI needs `contents: write` permission for the commit-and-push step. Update the `permissions` block in both workflows:

```yaml
permissions:
  id-token: write
  contents: write
```

**Step 4: Commit**

```bash
git add .github/actions/update-versions/action.yml .github/workflows/docker-build-executor.yml .github/workflows/docker-build-dashboard.yml
git commit -m "ci: auto-update versions.defaults.json after artifact builds"
```

---

### Task 9: Integration test — full boot with versions

**Files:**
- Create: `tests/cogos/image/test_versioned_boot.py`

**Step 1: Write integration test**

```python
# tests/cogos/image/test_versioned_boot.py
"""Integration test: boot with version manifest."""
import json
from pathlib import Path

from cogos.db.local_repository import LocalRepository
from cogos.files.store import FileStore
from cogos.image.apply import apply_image
from cogos.image.spec import load_image
from cogos.image.versions import (
    VersionManifest, load_defaults, resolve_versions, write_versions_to_filestore,
)


def test_boot_writes_versions(tmp_path):
    """Full boot writes versions.json to FileStore."""
    repo = LocalRepository(tmp_path / "data.json")

    # Load real image
    repo_root = Path(__file__).resolve().parents[4]
    image_dir = repo_root / "images" / "cogent-v1"
    assert image_dir.is_dir(), f"Image not found: {image_dir}"

    # Resolve versions (all local for test)
    defaults = load_defaults(image_dir)
    components = resolve_versions(defaults, {})

    # Write versions
    manifest = VersionManifest(epoch=repo.reboot_epoch, cogent_name="test", components=components)
    fs = FileStore(repo)
    write_versions_to_filestore(manifest, fs)

    # Boot image
    spec = load_image(image_dir)
    counts = apply_image(spec, repo)
    assert counts["processes"] > 0

    # Verify versions.json is in FileStore
    content = fs.get_content("mnt/boot/versions.json")
    assert content is not None
    data = json.loads(content)
    assert data["cogent_name"] == "test"
    assert "executor" in data["components"]
```

**Step 2: Run test**

Run: `cd /Users/daveey/code/cogents/cogents.1 && python -m pytest tests/cogos/image/test_versioned_boot.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/cogos/image/test_versioned_boot.py
git commit -m "test(versions): add integration test for versioned boot"
```
