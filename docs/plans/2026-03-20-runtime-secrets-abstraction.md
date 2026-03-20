# Runtime Secrets Abstraction — Remove Direct AWS Calls from CogOS

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** CogOS capabilities must never call AWS directly for secrets. All secret access goes through `CogtainerRuntime.get_secret()`, which each runtime implements differently.

**Architecture:** Add `get_secret(key, field?)` to `CogtainerRuntime`. Thread the runtime into the executor and capabilities. Replace all `fetch_secret()` and direct `boto3.client("ssm")`/`boto3.client("secretsmanager")` calls in `src/cogos/` with runtime delegation. The executor already receives env vars from the runtime — we add a `COGTAINER_TYPE` env var so it can reconstruct the right runtime for secret access.

**Tech Stack:** Python, boto3, pydantic, pytest

---

## Background

### Current Problem

CogOS capabilities directly call AWS SSM Parameter Store and Secrets Manager via:

1. **`SecretsCapability.get()`** (`src/cogos/capabilities/secrets.py:67-92`) — boto3 SSM then SecretsManager
2. **`_secrets_helper.fetch_secret()`** (`src/cogos/capabilities/_secrets_helper.py:12-55`) — same pattern, used by:
   - `web_search.py:102,147,191` — Tavily, GitHub, Twitter API keys
   - `github_cap.py:103` — GitHub token
   - `asana_cap.py:120,135` — Asana credentials
   - `image/_gemini_helper.py:23` — Gemini API key
   - `executor/llm_client.py:149` — Anthropic API key fallback
3. **`io/access.py:37,55`** — `get_io_token()` and `get_io_secret()` for Discord/IO channel tokens

### Architecture Constraint

The executor runs as a **separate process** (Lambda on AWS, subprocess locally). It does NOT receive the runtime object — it bootstraps from env vars via `get_config()` → `get_repo()`. We need a way for the executor to access secrets without receiving the runtime directly.

### Design Decision

Add a lightweight `SecretsProvider` protocol that the runtime creates and the executor can reconstruct from env vars. Two implementations:
- `AwsSecretsProvider` — SSM + SecretsManager (what exists today)
- `LocalSecretsProvider` — reads from a local JSON file at `{data_dir}/.secrets.json`

The executor reconstructs the provider from env vars (`SECRETS_PROVIDER=aws|local`, `COGOS_LOCAL_DATA`, etc.) alongside the repo.

---

## Task 1: Add `SecretsProvider` Protocol and Implementations

**Files:**
- Create: `src/cogtainer/secrets.py`
- Test: `tests/cogtainer/test_secrets.py`

**Step 1: Write the failing test**

```python
# tests/cogtainer/test_secrets.py
"""Tests for SecretsProvider implementations."""
import json
import pytest
from pathlib import Path


def test_local_secrets_provider_get(tmp_path):
    """LocalSecretsProvider reads from .secrets.json file."""
    from cogtainer.secrets import LocalSecretsProvider

    secrets_file = tmp_path / ".secrets.json"
    secrets_file.write_text(json.dumps({
        "my/key": "plain-value",
        "my/json-key": json.dumps({"api_key": "sk-123", "extra": "data"}),
    }))

    provider = LocalSecretsProvider(data_dir=str(tmp_path))
    assert provider.get_secret("my/key") == "plain-value"
    assert provider.get_secret("my/key", field="api_key") is None  # not JSON


def test_local_secrets_provider_get_field(tmp_path):
    """LocalSecretsProvider extracts field from JSON secret."""
    from cogtainer.secrets import LocalSecretsProvider

    secrets_file = tmp_path / ".secrets.json"
    secrets_file.write_text(json.dumps({
        "cogent/test/github": json.dumps({"access_token": "ghp_abc"}),
    }))

    provider = LocalSecretsProvider(data_dir=str(tmp_path))
    assert provider.get_secret("cogent/test/github", field="access_token") == "ghp_abc"


def test_local_secrets_provider_missing_key(tmp_path):
    """LocalSecretsProvider raises on missing key."""
    from cogtainer.secrets import LocalSecretsProvider

    secrets_file = tmp_path / ".secrets.json"
    secrets_file.write_text(json.dumps({}))

    provider = LocalSecretsProvider(data_dir=str(tmp_path))
    with pytest.raises(KeyError):
        provider.get_secret("nonexistent")


def test_local_secrets_provider_no_file(tmp_path):
    """LocalSecretsProvider raises when secrets file doesn't exist."""
    from cogtainer.secrets import LocalSecretsProvider

    provider = LocalSecretsProvider(data_dir=str(tmp_path))
    with pytest.raises(KeyError):
        provider.get_secret("any-key")


def test_local_secrets_provider_set_and_get(tmp_path):
    """LocalSecretsProvider.set_secret persists and is readable."""
    from cogtainer.secrets import LocalSecretsProvider

    provider = LocalSecretsProvider(data_dir=str(tmp_path))
    provider.set_secret("my/key", "my-value")
    assert provider.get_secret("my/key") == "my-value"


def test_aws_secrets_provider_protocol():
    """AwsSecretsProvider implements the protocol."""
    from cogtainer.secrets import AwsSecretsProvider, SecretsProvider

    # Just verify it's instantiable and has the right methods
    assert hasattr(AwsSecretsProvider, "get_secret")
    assert hasattr(AwsSecretsProvider, "set_secret")


def test_create_secrets_provider_local(tmp_path):
    """Factory creates LocalSecretsProvider for local type."""
    from cogtainer.secrets import create_secrets_provider, LocalSecretsProvider

    provider = create_secrets_provider(provider_type="local", data_dir=str(tmp_path))
    assert isinstance(provider, LocalSecretsProvider)


def test_create_secrets_provider_aws():
    """Factory creates AwsSecretsProvider for aws type."""
    from cogtainer.secrets import create_secrets_provider, AwsSecretsProvider

    provider = create_secrets_provider(provider_type="aws")
    assert isinstance(provider, AwsSecretsProvider)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogtainer/test_secrets.py -v`
Expected: FAIL — module not found

**Step 3: Write the implementation**

```python
# src/cogtainer/secrets.py
"""SecretsProvider — runtime-agnostic secret access."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class SecretsProvider(Protocol):
    """Protocol for secret retrieval — implemented per runtime."""

    def get_secret(self, key: str, field: str | None = None) -> str:
        """Fetch a secret by key. If field is set and value is JSON, extract that field.

        Raises KeyError if the secret doesn't exist.
        """
        ...

    def set_secret(self, key: str, value: str) -> None:
        """Store a secret value."""
        ...


def _extract_field(value: str, field: str | None, key: str) -> str:
    """Extract a field from a JSON secret value, or return raw value."""
    if field is None:
        return value
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict) and field in parsed:
            return parsed[field]
    except (json.JSONDecodeError, TypeError):
        pass
    return None


class LocalSecretsProvider:
    """Secrets from a local JSON file at {data_dir}/.secrets.json."""

    def __init__(self, data_dir: str) -> None:
        self._path = Path(data_dir) / ".secrets.json"

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text())

    def get_secret(self, key: str, field: str | None = None) -> str:
        secrets = self._load()
        if key not in secrets:
            raise KeyError(f"Secret not found: {key}")
        value = secrets[key]
        result = _extract_field(value, field, key)
        if result is None and field is not None:
            return value  # field not found, return raw
        return result if result is not None else value

    def set_secret(self, key: str, value: str) -> None:
        secrets = self._load()
        secrets[key] = value
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(secrets, indent=2))


class AwsSecretsProvider:
    """Secrets from AWS SSM Parameter Store + Secrets Manager fallback."""

    def __init__(self, region: str = "us-east-1", session: object | None = None) -> None:
        self._region = region
        self._session = session

    def _boto_client(self, service: str):
        import boto3
        if self._session and hasattr(self._session, "client"):
            return self._session.client(service, region_name=self._region)
        return boto3.client(service, region_name=self._region)

    def get_secret(self, key: str, field: str | None = None) -> str:
        # Try SSM Parameter Store first
        try:
            client = self._boto_client("ssm")
            resp = client.get_parameter(Name=key, WithDecryption=True)
            value = resp["Parameter"]["Value"]
            result = _extract_field(value, field, key)
            return result if result is not None else value
        except Exception:
            pass

        # Fallback to Secrets Manager
        try:
            client = self._boto_client("secretsmanager")
            resp = client.get_secret_value(SecretId=key)
            value = resp.get("SecretString")
            if value is None:
                raise KeyError(f"Secret '{key}' is binary, not string")
            result = _extract_field(value, field, key)
            return result if result is not None else value
        except KeyError:
            raise
        except Exception as exc:
            raise KeyError(f"Secret not found: {key} ({exc})") from exc

    def set_secret(self, key: str, value: str) -> None:
        client = self._boto_client("secretsmanager")
        try:
            client.put_secret_value(SecretId=key, SecretString=value)
        except Exception:
            client.create_secret(Name=key, SecretString=value)


def create_secrets_provider(
    provider_type: str = "aws",
    data_dir: str = "",
    region: str = "us-east-1",
    session: object | None = None,
) -> SecretsProvider:
    """Factory — create the right provider from config."""
    if provider_type in ("local", "docker"):
        return LocalSecretsProvider(data_dir=data_dir)
    if provider_type == "aws":
        return AwsSecretsProvider(region=region, session=session)
    raise ValueError(f"Unknown secrets provider type: {provider_type}")
```

**Step 4: Run tests**

Run: `python -m pytest tests/cogtainer/test_secrets.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogtainer/secrets.py tests/cogtainer/test_secrets.py
git commit -m "feat: add SecretsProvider protocol with local and AWS implementations"
```

---

## Task 2: Wire SecretsProvider into CogtainerRuntime

**Files:**
- Modify: `src/cogtainer/runtime/base.py`
- Modify: `src/cogtainer/runtime/local.py`
- Modify: `src/cogtainer/runtime/aws.py`
- Modify: `src/cogtainer/runtime/factory.py`

**Step 1: Add `get_secrets_provider()` to base runtime**

In `src/cogtainer/runtime/base.py`, add an abstract method:

```python
@abstractmethod
def get_secrets_provider(self) -> Any:
    """Return the SecretsProvider for this runtime."""
```

**Step 2: Implement in LocalRuntime**

In `src/cogtainer/runtime/local.py`, add to `__init__`:

```python
from cogtainer.secrets import LocalSecretsProvider
self._secrets = LocalSecretsProvider(data_dir=str(self._data_dir))
```

Add method:

```python
def get_secrets_provider(self):
    return self._secrets
```

**Step 3: Implement in AwsRuntime**

In `src/cogtainer/runtime/aws.py`, add to `__init__`:

```python
from cogtainer.secrets import AwsSecretsProvider
self._secrets = AwsSecretsProvider(region=self._region, session=session)
```

Add method:

```python
def get_secrets_provider(self):
    return self._secrets
```

**Step 4: Pass secrets env vars in LocalRuntime.spawn_executor**

In `src/cogtainer/runtime/local.py`, modify `spawn_executor` to pass `SECRETS_PROVIDER` and `COGOS_LOCAL_DATA`:

```python
def spawn_executor(self, cogent_name: str, process_id: str) -> None:
    cogent_dir = self._data_dir / cogent_name
    env = {
        **os.environ,
        "COGTAINER": self._entry.type,
        "COGENT": cogent_name,
        "USE_LOCAL_DB": "1",
        "COGOS_LOCAL_DATA": str(cogent_dir),
        "SECRETS_PROVIDER": "local",
        "SECRETS_DATA_DIR": str(self._data_dir),
    }
    subprocess.Popen(
        [sys.executable, "-m", "cogos.executor", process_id],
        env=env,
    )
```

**Step 5: Run existing tests**

Run: `python -m pytest tests/cogtainer/ -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/cogtainer/runtime/base.py src/cogtainer/runtime/local.py src/cogtainer/runtime/aws.py
git commit -m "feat: wire SecretsProvider into CogtainerRuntime implementations"
```

---

## Task 3: Make SecretsProvider Available to the Executor

**Files:**
- Modify: `src/cogos/executor/handler.py` (lines 64-93)

The executor runs as a separate process and bootstraps from env vars. Add a `get_secrets_provider()` function alongside `get_repo()`.

**Step 1: Add provider reconstruction to handler.py**

After the existing `get_repo()` function (line 86-93), add:

```python
def get_secrets_provider():
    """Reconstruct SecretsProvider from env vars set by the runtime."""
    from cogtainer.secrets import create_secrets_provider

    provider_type = os.environ.get("SECRETS_PROVIDER", "aws")
    data_dir = os.environ.get("SECRETS_DATA_DIR", os.environ.get("COGOS_LOCAL_DATA", ""))
    region = os.environ.get("AWS_REGION", "us-east-1")
    return create_secrets_provider(
        provider_type=provider_type,
        data_dir=data_dir,
        region=region,
    )
```

**Step 2: Store provider as module-level singleton**

In `handler()` function, after `repo = get_repo(config)`, add:

```python
_secrets_provider = get_secrets_provider()
```

And make it accessible:

```python
_SECRETS_PROVIDER = None

def _get_secrets_provider():
    global _SECRETS_PROVIDER
    if _SECRETS_PROVIDER is None:
        _SECRETS_PROVIDER = get_secrets_provider()
    return _SECRETS_PROVIDER
```

**Step 3: Commit**

```bash
git add src/cogos/executor/handler.py
git commit -m "feat: executor bootstraps SecretsProvider from env vars"
```

---

## Task 4: Thread SecretsProvider into Capabilities

**Files:**
- Modify: `src/cogos/capabilities/base.py` (lines 156-163)
- Modify: `src/cogos/executor/handler.py` (line 1232)

**Step 1: Add optional `secrets_provider` to Capability base**

In `src/cogos/capabilities/base.py`, modify `__init__`:

```python
def __init__(
    self, repo: Repository, process_id: UUID,
    run_id: UUID | None = None, trace_id: UUID | None = None,
    secrets_provider: Any = None,
) -> None:
    self.repo = repo
    self.process_id = process_id
    self.run_id = run_id
    self.trace_id = trace_id
    self._scope = {}
    self._secrets_provider = secrets_provider
```

**Step 2: Pass secrets_provider in `_setup_capability_proxies`**

In `src/cogos/executor/handler.py`, at line 1232 where capabilities are instantiated:

```python
# Change from:
instance = handler_cls(repo, process.id, **kwargs)

# Change to:
if "secrets_provider" in init_params or has_var_keyword:
    kwargs["secrets_provider"] = _get_secrets_provider()
instance = handler_cls(repo, process.id, **kwargs)
```

**Step 3: Run existing tests**

Run: `python -m pytest tests/ -k "capability or handler" -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/cogos/capabilities/base.py src/cogos/executor/handler.py
git commit -m "feat: thread SecretsProvider into Capability base class"
```

---

## Task 5: Replace `_secrets_helper.fetch_secret()` with Provider

**Files:**
- Modify: `src/cogos/capabilities/_secrets_helper.py`

This is the central fix. Replace the boto3 calls with a function that uses the provider. Since many callers don't have a provider reference, make `fetch_secret()` accept an optional provider and fall back to reconstructing one from env vars.

**Step 1: Rewrite `_secrets_helper.py`**

```python
"""Shared secret fetching — delegates to SecretsProvider."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def fetch_secret(key: str, field: str | None = None, *, secrets_provider=None) -> str:
    """Fetch a secret value via the runtime's SecretsProvider.

    If `key` contains ``{cogent}``, it is replaced with the ``COGENT_NAME``
    environment variable.

    If `secrets_provider` is not given, reconstructs one from env vars.
    """
    # Resolve {cogent} placeholder
    if "{cogent}" in key:
        cogent_name = os.environ.get("COGENT_NAME", "")
        if not cogent_name:
            raise RuntimeError(
                f"Secret key '{key}' contains {{cogent}} but COGENT_NAME env var is not set"
            )
        key = key.replace("{cogent}", cogent_name)

    if secrets_provider is None:
        from cogtainer.secrets import create_secrets_provider

        provider_type = os.environ.get("SECRETS_PROVIDER", "aws")
        data_dir = os.environ.get("SECRETS_DATA_DIR", os.environ.get("COGOS_LOCAL_DATA", ""))
        region = os.environ.get("AWS_REGION", "us-east-1")
        secrets_provider = create_secrets_provider(
            provider_type=provider_type,
            data_dir=data_dir,
            region=region,
        )

    try:
        return secrets_provider.get_secret(key, field=field)
    except KeyError as exc:
        raise RuntimeError(f"Could not fetch secret '{key}': {exc}") from exc
```

**Step 2: Run tests**

Run: `python -m pytest tests/ -k "secret" -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/cogos/capabilities/_secrets_helper.py
git commit -m "refactor: _secrets_helper delegates to SecretsProvider instead of boto3"
```

---

## Task 6: Replace SecretsCapability with Provider Delegation

**Files:**
- Modify: `src/cogos/capabilities/secrets.py`

**Step 1: Rewrite `SecretsCapability.get()` to use the provider**

```python
def get(self, key: str) -> SecretValue | SecretError:
    self._check("get", key=key)
    try:
        value = self._secrets_provider.get_secret(key)
        # Try to parse JSON
        try:
            import json
            parsed = json.loads(value)
            return SecretValue(key=key, value=parsed)
        except (json.JSONDecodeError, TypeError):
            return SecretValue(key=key, value=value)
    except (KeyError, Exception) as exc:
        return SecretError(key=key, error=str(exc))
```

Remove the `import boto3` from the method.

**Step 2: Run tests**

Run: `python -m pytest tests/ -k "secret" -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/cogos/capabilities/secrets.py
git commit -m "refactor: SecretsCapability delegates to runtime SecretsProvider"
```

---

## Task 7: Update Capability Callers to Use Provider

**Files:**
- Modify: `src/cogos/capabilities/web_search.py` (lines 102, 147, 191)
- Modify: `src/cogos/capabilities/github_cap.py` (line 103)
- Modify: `src/cogos/capabilities/asana_cap.py` (lines 120, 135)
- Modify: `src/cogos/capabilities/image/_gemini_helper.py` (line 23)

These capabilities all inherit from `Capability` and now have `self._secrets_provider`. Update their `fetch_secret()` calls to pass the provider.

**Step 1: Update web_search.py**

Change all three `fetch_secret(...)` calls to `fetch_secret(..., secrets_provider=self._secrets_provider)`:

```python
# Line 102
api_key = fetch_secret("cogent/{cogent}/tavily", field="api_key", secrets_provider=self._secrets_provider)
# Line 147
token = fetch_secret("cogent/{cogent}/github", field="access_token", secrets_provider=self._secrets_provider)
# Line 191
bearer = fetch_secret("cogent/{cogent}/twitter", field="bearer_token", secrets_provider=self._secrets_provider)
```

**Step 2: Update github_cap.py**

```python
# Line 103
secret_raw = fetch_secret(SECRET_KEY, secrets_provider=self._secrets_provider)
```

**Step 3: Update asana_cap.py**

```python
# Line 120
self._username = fetch_secret("cogent/{cogent}/asana", field="username", secrets_provider=self._secrets_provider) or ""
# Line 135
self._api_key = fetch_secret(SECRET_KEY, field="access_token", secrets_provider=self._secrets_provider)
```

**Step 4: Update image/_gemini_helper.py**

This is a standalone function, not a capability method. It needs to accept a provider parameter:

```python
def get_gemini_client(secrets_provider=None):
    from cogos.capabilities._secrets_helper import fetch_secret
    api_key = fetch_secret("cogent/{cogent}/gemini", field="api_key", secrets_provider=secrets_provider)
    ...
```

Then update callers of `get_gemini_client()` in the ImageCapability to pass `self._secrets_provider`.

**Step 5: Run tests**

Run: `python -m pytest tests/ -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/cogos/capabilities/web_search.py src/cogos/capabilities/github_cap.py src/cogos/capabilities/asana_cap.py src/cogos/capabilities/image/_gemini_helper.py
git commit -m "refactor: all capability secret calls go through SecretsProvider"
```

---

## Task 8: Update executor/llm_client.py

**Files:**
- Modify: `src/cogos/executor/llm_client.py` (lines 140-152)

**Step 1: Update `_resolve_anthropic_api_key` to use provider**

```python
def _resolve_anthropic_api_key(explicit_key: str | None = None) -> str | None:
    """Resolve Anthropic API key: explicit arg > env var > secrets provider."""
    if explicit_key:
        return explicit_key
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return env_key
    try:
        from cogos.capabilities._secrets_helper import fetch_secret
        return fetch_secret(ANTHROPIC_SECRET_PATH, field="api_key")
    except Exception as exc:
        logger.debug("Could not fetch Anthropic key from secrets: %s", exc)
        return None
```

Note: This function already works because `fetch_secret()` now reconstructs a provider from env vars when none is passed. No change needed if env vars are set. But verify it works.

**Step 2: Commit**

```bash
git add src/cogos/executor/llm_client.py
git commit -m "refactor: llm_client secret access goes through SecretsProvider"
```

---

## Task 9: Update io/access.py

**Files:**
- Modify: `src/cogos/io/access.py` (lines 15-57)

**Step 1: Replace direct boto3 calls with SecretsProvider**

```python
"""IO access token retrieval — delegates to SecretsProvider."""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)


def get_io_token(cogent_name: str, channel: str) -> str:
    """Return the bot/access token for a cogent's IO channel."""
    from cogos.capabilities._secrets_helper import fetch_secret

    secret_id = f"identity_service/{cogent_name}/{channel}"
    raw = fetch_secret(secret_id)
    try:
        parsed = json.loads(raw)
        return parsed.get("token", raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def get_io_secret(cogent_name: str, channel: str) -> dict:
    """Return the full secret dict for a cogent's IO channel."""
    from cogos.capabilities._secrets_helper import fetch_secret

    secret_id = f"identity_service/{cogent_name}/{channel}"
    raw = fetch_secret(secret_id)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"token": raw}
```

**Step 2: Commit**

```bash
git add src/cogos/io/access.py
git commit -m "refactor: io/access.py delegates to SecretsProvider via fetch_secret"
```

---

## Task 10: Update remaining io/ files with direct AWS calls

**Files:**
- Modify: `src/cogos/io/discord/setup.py` — secret reads
- Modify: `src/cogos/io/discord/registry.py` — secret reads
- Modify: `src/cogos/io/cli.py` — secret list/read/delete

These are CLI/admin tools. They can use `fetch_secret()` for reads, but for listing and deleting secrets they need the provider directly. Add `list_secrets(prefix)` and `delete_secret(key)` to `SecretsProvider`.

**Step 1: Add list/delete to providers**

In `src/cogtainer/secrets.py`, add to `SecretsProvider` protocol:

```python
def list_secrets(self, prefix: str) -> list[str]:
    """List secret keys matching a prefix."""
    ...

def delete_secret(self, key: str) -> None:
    """Delete a secret."""
    ...
```

Implement in `LocalSecretsProvider`:

```python
def list_secrets(self, prefix: str) -> list[str]:
    secrets = self._load()
    return [k for k in secrets if k.startswith(prefix)]

def delete_secret(self, key: str) -> None:
    secrets = self._load()
    secrets.pop(key, None)
    self._path.write_text(json.dumps(secrets, indent=2))
```

Implement in `AwsSecretsProvider`:

```python
def list_secrets(self, prefix: str) -> list[str]:
    client = self._boto_client("secretsmanager")
    keys = []
    paginator = client.get_paginator("list_secrets")
    for page in paginator.paginate(Filters=[{"Key": "name", "Values": [prefix]}]):
        for secret in page.get("SecretList", []):
            keys.append(secret["Name"])
    return keys

def delete_secret(self, key: str) -> None:
    client = self._boto_client("secretsmanager")
    client.delete_secret(SecretId=key, ForceDeleteWithoutRecovery=True)
```

**Step 2: Update `io/cli.py` to use provider**

Replace the 3 `boto3.client("secretsmanager")` calls with `fetch_secret()` for reads and `create_secrets_provider()` for list/delete operations.

**Step 3: Update `io/discord/setup.py`**

Replace `boto3.client("secretsmanager")` calls with `fetch_secret()`. The ECS call (`discord_service_status`) is not secrets-related — leave it for now (it's admin tooling, not cogos runtime).

**Step 4: Update `io/discord/registry.py`**

Replace `boto3.client("secretsmanager")` call in `_read_persona_secret()` with `fetch_secret()`.

**Step 5: Commit**

```bash
git add src/cogtainer/secrets.py src/cogos/io/cli.py src/cogos/io/discord/setup.py src/cogos/io/discord/registry.py
git commit -m "refactor: io/ secret access goes through SecretsProvider"
```

---

## Task 11: Update registry description for secrets capability

**Files:**
- Modify: `src/cogos/capabilities/registry.py` (line 394)

**Step 1: Update the description**

Change the secrets capability description from:
```python
"description": "Retrieve secrets from AWS SSM Parameter Store or Secrets Manager.",
```
To:
```python
"description": "Retrieve secrets from the runtime's secret store.",
```

And update instructions:
```python
"instructions": (
    "Use secrets to retrieve API keys, tokens, and other sensitive values.\n"
    "- secrets.get(key) — retrieve a secret by name\n"
    "The secret store is provided by the cogtainer runtime.\n"
    "JSON values are automatically parsed. Never log or emit secret values."
),
```

**Step 2: Commit**

```bash
git add src/cogos/capabilities/registry.py
git commit -m "docs: update secrets capability description to be runtime-agnostic"
```

---

## Task 12: Verify — grep for remaining boto3 in cogos capabilities

**Step 1: Search for any remaining direct AWS calls in capabilities**

Run: `grep -rn "boto3" src/cogos/capabilities/`
Expected: Zero matches (all boto3 calls removed from capabilities)

Run: `grep -rn "boto3" src/cogos/io/access.py`
Expected: Zero matches

**Step 2: Search for remaining fetch_secret without provider**

Run: `grep -rn "fetch_secret(" src/cogos/ | grep -v "secrets_provider" | grep -v "_secrets_helper.py" | grep -v "test_"`
Expected: Only `llm_client.py` (which relies on env-var fallback, acceptable) and any that pass the provider

**Step 3: Commit final cleanup if needed**

---

## Out of Scope (Do Later)

These files also have direct boto3 calls but are **not capabilities** — they're infrastructure/IO services that run in their own containers:

- `src/cogos/io/discord/bridge.py` — SQS + S3 (runs as its own ECS service)
- `src/cogos/io/discord/capability.py` — SQS send (Discord reply queue)
- `src/cogos/io/discord/reply.py` — SQS send (Discord reply queue)
- `src/cogos/io/email/sender.py` — SES (email sending)
- `src/cogos/io/email/provision.py` — SES verification
- `src/cogos/capabilities/blob.py` — S3 (blob storage)
- `src/cogos/db/repository.py` — RDS Data API + SQS nudge
- `src/cogos/executor/llm_client.py` — Bedrock client (LLM calls)
- `src/cogos/shell/` — interactive shell tooling
- `src/cogos/cli/__main__.py` — CLI admin commands

These should be addressed in a follow-up to route **all** AWS service access through the runtime (not just secrets). The secrets abstraction is the first step.
