# Capability Scoping Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `_scope`, `scope()`, `_narrow()`, and `_check()` to the Capability base class and all subclasses, replace inline proxy classes in the executor with real capability instances that honor scope config from `ProcessCapability.config`.

**Architecture:** The base `Capability` class gets a `_scope` dict and three new methods. Each subclass overrides `_narrow()` (intersection logic) and `_check()` (enforcement). The executor's `_setup_capability_proxies` replaces inline `FilesProxy`/`ProcsProxy`/`EventsProxy` with real capability class instances, applying `.scope(**config)` from `ProcessCapability.config` at boot. The existing `FilesCapability` is kept but split conceptually — `file`, `file_version`, `dir` are new classes for fine-grained grants; the original `FilesCapability` remains as the "files" capability for backwards compat.

**Tech Stack:** Python 3.12, Pydantic, pytest, fnmatch (for event pattern matching)

---

### Task 1: Base Capability — add `_scope`, `scope()`, `_narrow()`, `_check()`

**Files:**
- Modify: `src/cogos/capabilities/base.py:114-148`
- Test: `tests/cogos/capabilities/test_base_scoping.py`

**Step 1: Write the failing test**

Create `tests/cogos/capabilities/test_base_scoping.py`:

```python
"""Tests for base Capability scoping mechanism."""

from __future__ import annotations

from copy import copy
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.base import Capability


class DummyCapability(Capability):
    """Concrete subclass for testing base scoping."""

    ALL_OPS = {"read", "write", "delete"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        return {"ops": sorted(old_ops & new_ops)}

    def _check(self, op: str, **context) -> None:
        if not self._scope:
            return
        allowed = set(self._scope.get("ops") or self.ALL_OPS)
        if op not in allowed:
            raise PermissionError(f"Operation '{op}' not allowed. Allowed: {allowed}")

    def read(self) -> str:
        self._check("read")
        return "ok"

    def write(self) -> str:
        self._check("write")
        return "ok"


def _make(scope=None):
    repo = MagicMock()
    cap = DummyCapability(repo, uuid4())
    if scope:
        cap = cap.scope(**scope)
    return cap


class TestBaseScoping:
    def test_unscoped_has_empty_scope(self):
        cap = _make()
        assert cap._scope == {}

    def test_scope_returns_new_instance(self):
        cap = _make()
        scoped = cap.scope(ops=["read"])
        assert scoped is not cap
        assert cap._scope == {}
        assert scoped._scope == {"ops": ["read"]}

    def test_scope_preserves_repo_and_process_id(self):
        repo = MagicMock()
        pid = uuid4()
        cap = DummyCapability(repo, pid)
        scoped = cap.scope(ops=["read"])
        assert scoped.repo is repo
        assert scoped.process_id == pid

    def test_scope_narrows_only(self):
        cap = _make(scope={"ops": ["read", "write"]})
        narrower = cap.scope(ops=["read", "delete"])
        assert set(narrower._scope["ops"]) == {"read"}  # intersection

    def test_check_allows_permitted_op(self):
        cap = _make(scope={"ops": ["read"]})
        cap.read()  # should not raise

    def test_check_denies_unpermitted_op(self):
        cap = _make(scope={"ops": ["read"]})
        with pytest.raises(PermissionError, match="write"):
            cap.write()

    def test_unscoped_allows_everything(self):
        cap = _make()
        cap.read()
        cap.write()  # both should work
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/capabilities/test_base_scoping.py -v`
Expected: FAIL — `Capability` has no `_scope` attribute, no `scope()` method

**Step 3: Write minimal implementation**

In `src/cogos/capabilities/base.py`, modify `class Capability` (line 114):

```python
class Capability:
    """Base class for CogOS capabilities.

    Subclasses define typed methods that processes call in the sandbox.
    Each capability is instantiated once per process session with a
    repository handle and the owning process ID.

    Scoping: every instance has a `_scope` dict (empty = unrestricted).
    `.scope(**kwargs)` clones the instance with narrowed restrictions.
    Subclasses override `_narrow()` and `_check()`.
    """

    _scope: dict

    def __init__(self, repo: Repository, process_id: UUID) -> None:
        self.repo = repo
        self.process_id = process_id
        self._scope = {}

    def scope(self, **kwargs) -> "Capability":
        """Return a new instance with narrowed scope. Can only narrow, never widen."""
        from copy import copy
        new_scope = self._narrow(self._scope, kwargs)
        clone = copy(self)
        clone._scope = new_scope
        return clone

    def _narrow(self, existing: dict, requested: dict) -> dict:
        """Intersect existing scope with requested. Subclasses override."""
        return {**existing, **requested}

    def _check(self, op: str, **context) -> None:
        """Raise PermissionError if op is not allowed. Subclasses override."""
        pass  # base: no enforcement (unscoped = allow all)

    def help(self) -> str:
        # ... existing help() method unchanged ...
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/capabilities/test_base_scoping.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add src/cogos/capabilities/base.py tests/cogos/capabilities/test_base_scoping.py
git commit -m "feat: add _scope, scope(), _narrow(), _check() to Capability base class"
```

---

### Task 2: EventsCapability — add scoping

**Files:**
- Modify: `src/cogos/capabilities/events.py:42-89`
- Test: `tests/cogos/capabilities/test_events_scoping.py`

**Step 1: Write the failing test**

Create `tests/cogos/capabilities/test_events_scoping.py`:

```python
"""Tests for EventsCapability scoping."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.capabilities.events import EventsCapability


def _make(scope=None):
    repo = MagicMock()
    repo.append_event.return_value = uuid4()
    repo.get_events.return_value = []
    cap = EventsCapability(repo, uuid4())
    if scope:
        cap = cap.scope(**scope)
    return cap


class TestEventsScoping:
    def test_unscoped_allows_any_emit(self):
        cap = _make()
        result = cap.emit("anything:here")
        assert hasattr(result, "id")

    def test_scoped_emit_allows_matching_pattern(self):
        cap = _make(scope={"emit": ["task:*"]})
        result = cap.emit("task:completed")
        assert hasattr(result, "id")

    def test_scoped_emit_denies_non_matching(self):
        cap = _make(scope={"emit": ["task:*"]})
        with pytest.raises(PermissionError, match="emit.*email"):
            cap.emit("email:sent")

    def test_scoped_query_allows_matching(self):
        cap = _make(scope={"query": ["task:*"]})
        cap.query("task:completed")  # should not raise

    def test_scoped_query_denies_non_matching(self):
        cap = _make(scope={"query": ["task:*"]})
        with pytest.raises(PermissionError, match="query.*email"):
            cap.query("email:received")

    def test_narrow_intersects_emit_patterns(self):
        cap = _make(scope={"emit": ["task:*", "email:*"]})
        narrower = cap.scope(emit=["task:*", "discord:*"])
        assert set(narrower._scope["emit"]) == {"task:*"}

    def test_narrow_intersects_query_patterns(self):
        cap = _make(scope={"query": ["*"]})
        narrower = cap.scope(query=["task:*"])
        # "*" intersected with ["task:*"] — since "*" is a superset, keeps the narrower
        assert narrower._scope["query"] == ["task:*"]

    def test_unscoped_query_no_filter(self):
        cap = _make()
        cap.query()  # None event_type should work unscoped
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/capabilities/test_events_scoping.py -v`
Expected: FAIL — `_check` not called, no `_narrow` override

**Step 3: Write minimal implementation**

In `src/cogos/capabilities/events.py`, add scoping to `EventsCapability`:

```python
import fnmatch

class EventsCapability(Capability):
    """Append-only event log.

    Usage:
        events.emit("task:completed", {"task_id": "123"})
        events.query("email:received", limit=10)

    Scoping:
        events.scope(emit=["task:*"], query=["task:*", "email:*"])
    """

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result = {}
        for key in ("emit", "query"):
            old = existing.get(key)
            new = requested.get(key)
            if old is None and new is None:
                continue
            if old is None:
                result[key] = new
            elif new is None:
                result[key] = old
            elif "*" in old:
                result[key] = new
            elif "*" in new:
                result[key] = old
            else:
                result[key] = sorted(set(old) & set(new))
        return result

    def _check(self, op: str, **context) -> None:
        if not self._scope:
            return
        patterns = self._scope.get(op)
        if patterns is None:
            return  # no restriction on this op
        target = context.get("event_type", "")
        if not target:
            return  # query with no filter is OK
        if not any(fnmatch.fnmatch(target, p) for p in patterns):
            raise PermissionError(
                f"Cannot {op} '{target}'. Allowed patterns: {patterns}"
            )

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        parent_event: str | None = None,
    ) -> EmitResult | EventError:
        if not event_type:
            return EventError(error="event_type is required")
        self._check("emit", event_type=event_type)
        # ... rest unchanged ...

    def query(self, event_type: str | None = None, limit: int = 100) -> list[EventRecord]:
        self._check("query", event_type=event_type or "")
        # ... rest unchanged ...
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/capabilities/test_events_scoping.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add src/cogos/capabilities/events.py tests/cogos/capabilities/test_events_scoping.py
git commit -m "feat: add scoping to EventsCapability with fnmatch patterns"
```

---

### Task 3: ProcsCapability — add scoping

**Files:**
- Modify: `src/cogos/capabilities/procs.py:54-172`
- Test: `tests/cogos/capabilities/test_procs_scoping.py`

**Step 1: Write the failing test**

Create `tests/cogos/capabilities/test_procs_scoping.py`:

```python
"""Tests for ProcsCapability scoping."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.procs import ProcsCapability


def _make(scope=None):
    repo = MagicMock()
    repo.list_processes.return_value = []
    repo.get_process_by_name.return_value = None
    cap = ProcsCapability(repo, uuid4())
    if scope:
        cap = cap.scope(**scope)
    return cap


class TestProcsScoping:
    def test_unscoped_allows_all(self):
        cap = _make()
        cap.list()  # should not raise

    def test_scoped_allows_permitted_ops(self):
        cap = _make(scope={"ops": ["list", "get"]})
        cap.list()  # should not raise

    def test_scoped_denies_spawn(self):
        cap = _make(scope={"ops": ["list", "get"]})
        with pytest.raises(PermissionError, match="spawn"):
            cap.spawn(name="test")

    def test_narrow_intersects_ops(self):
        cap = _make(scope={"ops": ["list", "get", "spawn"]})
        narrower = cap.scope(ops=["list", "spawn"])
        assert set(narrower._scope["ops"]) == {"list", "spawn"}
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/capabilities/test_procs_scoping.py -v`
Expected: FAIL — no `_check` enforcement

**Step 3: Write minimal implementation**

In `src/cogos/capabilities/procs.py`, add scoping to `ProcsCapability`:

```python
class ProcsCapability(Capability):
    """Process management. ...existing docstring..."""

    ALL_OPS = {"list", "get", "spawn"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        return {"ops": sorted(old_ops & new_ops)}

    def _check(self, op: str, **context) -> None:
        if not self._scope:
            return
        allowed = set(self._scope.get("ops") or self.ALL_OPS)
        if op not in allowed:
            raise PermissionError(f"Operation '{op}' not allowed. Allowed: {allowed}")

    def list(self, status: str | None = None, limit: int = 200) -> list[ProcessSummary]:
        self._check("list")
        # ... rest unchanged ...

    def get(self, name: str | None = None, id: str | None = None) -> ProcessDetail | ProcessError:
        self._check("get")
        # ... rest unchanged ...

    def spawn(self, name: str, ...) -> SpawnResult | ProcessError:
        self._check("spawn")
        # ... rest unchanged ...
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/capabilities/test_procs_scoping.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/cogos/capabilities/procs.py tests/cogos/capabilities/test_procs_scoping.py
git commit -m "feat: add scoping to ProcsCapability"
```

---

### Task 4: FilesCapability — add scoping (preserves existing class)

**Files:**
- Modify: `src/cogos/capabilities/files.py:48-109`
- Test: `tests/cogos/capabilities/test_files_scoping.py`

**Step 1: Write the failing test**

Create `tests/cogos/capabilities/test_files_scoping.py`:

```python
"""Tests for FilesCapability scoping."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.files import FilesCapability


def _make(scope=None):
    repo = MagicMock()
    repo.get_active_file_version.return_value = None
    cap = FilesCapability(repo, uuid4())
    if scope:
        cap = cap.scope(**scope)
    return cap


class TestFilesScoping:
    def test_unscoped_allows_any_key(self):
        cap = _make()
        cap.read("anything")  # should not raise (returns FileError, not PermissionError)

    def test_scoped_prefix_allows_matching_key(self):
        cap = _make(scope={"prefix": "/config/"})
        cap.read("/config/system")  # no PermissionError (may return FileError)

    def test_scoped_prefix_denies_outside_key(self):
        cap = _make(scope={"prefix": "/config/"})
        with pytest.raises(PermissionError, match="/secret"):
            cap.read("/secret/key")

    def test_scoped_ops_denies_write(self):
        cap = _make(scope={"ops": ["read", "search"]})
        with pytest.raises(PermissionError, match="write"):
            cap.write("/config/system", "content")

    def test_scoped_ops_allows_read(self):
        cap = _make(scope={"ops": ["read"]})
        cap.read("/any/key")  # should not raise PermissionError

    def test_narrow_prefix_can_only_narrow(self):
        cap = _make(scope={"prefix": "/config/"})
        narrower = cap.scope(prefix="/config/sub/")
        assert narrower._scope["prefix"] == "/config/sub/"

    def test_narrow_prefix_cannot_widen(self):
        cap = _make(scope={"prefix": "/config/"})
        with pytest.raises(ValueError, match="Cannot widen"):
            cap.scope(prefix="/other/")

    def test_narrow_ops_intersects(self):
        cap = _make(scope={"ops": ["read", "write", "search"]})
        narrower = cap.scope(ops=["read", "search"])
        assert set(narrower._scope["ops"]) == {"read", "search"}
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/capabilities/test_files_scoping.py -v`
Expected: FAIL — no `_check` enforcement

**Step 3: Write minimal implementation**

In `src/cogos/capabilities/files.py`, add scoping:

```python
class FilesCapability(Capability):
    """Versioned file store. ...existing docstring..."""

    ALL_OPS = {"read", "write", "search"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result = {}
        # Prefix narrowing
        old_prefix = existing.get("prefix")
        new_prefix = requested.get("prefix")
        if old_prefix and new_prefix:
            if not new_prefix.startswith(old_prefix):
                raise ValueError(f"Cannot widen prefix from {old_prefix} to {new_prefix}")
            result["prefix"] = new_prefix
        elif new_prefix:
            result["prefix"] = new_prefix
        elif old_prefix:
            result["prefix"] = old_prefix

        # Ops narrowing
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        result["ops"] = sorted(old_ops & new_ops)
        return result

    def _check(self, op: str, **context) -> None:
        if not self._scope:
            return
        # Check ops
        allowed = set(self._scope.get("ops") or self.ALL_OPS)
        if op not in allowed:
            raise PermissionError(f"Operation '{op}' not allowed. Allowed: {allowed}")
        # Check prefix
        prefix = self._scope.get("prefix")
        key = context.get("key", "")
        if prefix and key and not key.startswith(prefix):
            raise PermissionError(f"Key '{key}' outside allowed prefix '{prefix}'")

    def read(self, key: str) -> FileContent | FileError:
        if not key:
            return FileError(error="key is required")
        self._check("read", key=key)
        # ... rest unchanged ...

    def write(self, key: str, content: str, ...) -> FileWriteResult | FileError:
        if not key:
            return FileError(error="key is required")
        self._check("write", key=key)
        # ... rest unchanged ...

    def search(self, prefix: str | None = None, limit: int = 50) -> list[FileSearchResult]:
        self._check("search", key=prefix or "")
        # ... rest unchanged ...
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/capabilities/test_files_scoping.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add src/cogos/capabilities/files.py tests/cogos/capabilities/test_files_scoping.py
git commit -m "feat: add scoping to FilesCapability with prefix + ops enforcement"
```

---

### Task 5: DiscordCapability — add scoping

**Files:**
- Modify: `src/cogos/io/discord/capability.py:68-179`
- Test: `tests/cogos/io/test_discord_scoping.py`

**Step 1: Write the failing test**

Create `tests/cogos/io/test_discord_scoping.py`:

```python
"""Tests for DiscordCapability scoping."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.io.discord.capability import DiscordCapability


def _make(scope=None):
    repo = MagicMock()
    repo.get_events.return_value = []
    cap = DiscordCapability(repo, uuid4())
    if scope:
        cap = cap.scope(**scope)
    return cap


class TestDiscordScoping:
    @patch("cogos.io.discord.capability._send_sqs")
    def test_unscoped_allows_any_channel(self, mock_sqs):
        cap = _make()
        cap.send("any-channel", "hi")

    @patch("cogos.io.discord.capability._send_sqs")
    def test_scoped_channels_allows_matching(self, mock_sqs):
        cap = _make(scope={"channels": ["ch1", "ch2"]})
        cap.send("ch1", "hi")

    def test_scoped_channels_denies_non_matching(self):
        cap = _make(scope={"channels": ["ch1"]})
        with pytest.raises(PermissionError, match="ch2"):
            cap.send("ch2", "hi")

    def test_scoped_ops_denies_dm(self):
        cap = _make(scope={"ops": ["send", "receive"]})
        with pytest.raises(PermissionError, match="dm"):
            cap.dm("user1", "hi")

    def test_narrow_intersects_channels(self):
        cap = _make(scope={"channels": ["ch1", "ch2", "ch3"]})
        narrower = cap.scope(channels=["ch1", "ch3", "ch4"])
        assert set(narrower._scope["channels"]) == {"ch1", "ch3"}

    def test_narrow_intersects_ops(self):
        cap = _make(scope={"ops": ["send", "react", "dm"]})
        narrower = cap.scope(ops=["send", "receive"])
        assert set(narrower._scope["ops"]) == {"send"}
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/io/test_discord_scoping.py -v`
Expected: FAIL — no `_check` enforcement

**Step 3: Write minimal implementation**

In `src/cogos/io/discord/capability.py`, add scoping:

```python
class DiscordCapability(Capability):
    """Send and receive Discord messages. ...existing docstring..."""

    ALL_OPS = {"send", "react", "create_thread", "dm", "receive"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result = {}
        # Channels
        old_ch = existing.get("channels")
        new_ch = requested.get("channels")
        if old_ch is not None and new_ch is not None:
            result["channels"] = sorted(set(old_ch) & set(new_ch))
        elif new_ch is not None:
            result["channels"] = new_ch
        elif old_ch is not None:
            result["channels"] = old_ch

        # Ops
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        result["ops"] = sorted(old_ops & new_ops)
        return result

    def _check(self, op: str, **context) -> None:
        if not self._scope:
            return
        allowed_ops = set(self._scope.get("ops") or self.ALL_OPS)
        if op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not allowed. Allowed: {allowed_ops}")
        channel = context.get("channel")
        allowed_channels = self._scope.get("channels")
        if channel and allowed_channels is not None and channel not in allowed_channels:
            raise PermissionError(f"Channel '{channel}' not allowed. Allowed: {allowed_channels}")

    # Add self._check("send", channel=channel) at top of send()
    # Add self._check("react", channel=channel) at top of react()
    # Add self._check("create_thread", channel=channel) at top of create_thread()
    # Add self._check("dm") at top of dm()
    # Add self._check("receive") at top of receive()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/io/test_discord_scoping.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add src/cogos/io/discord/capability.py tests/cogos/io/test_discord_scoping.py
git commit -m "feat: add scoping to DiscordCapability with channels + ops"
```

---

### Task 6: EmailCapability — add scoping

**Files:**
- Modify: `src/cogos/io/email/capability.py:64-91`
- Test: `tests/cogos/io/test_email_scoping.py`

**Step 1: Write the failing test**

Create `tests/cogos/io/test_email_scoping.py`:

```python
"""Tests for EmailCapability scoping."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.io.email.capability import EmailCapability


def _make(scope=None):
    repo = MagicMock()
    repo.get_events.return_value = []
    cap = EmailCapability(repo, uuid4())
    if scope:
        cap = cap.scope(**scope)
    return cap


class TestEmailScoping:
    @patch("cogos.io.email.capability._get_sender")
    def test_scoped_to_allows_matching(self, mock_sender):
        mock_sender.return_value.send.return_value = {"MessageId": "123"}
        cap = _make(scope={"to": ["ok@example.com"]})
        cap.send(to="ok@example.com", subject="hi", body="hello")

    def test_scoped_to_denies_non_matching(self):
        cap = _make(scope={"to": ["ok@example.com"]})
        with pytest.raises(PermissionError, match="bad@example.com"):
            cap.send(to="bad@example.com", subject="hi", body="hello")

    def test_scoped_ops_denies_send(self):
        cap = _make(scope={"ops": ["receive"]})
        with pytest.raises(PermissionError, match="send"):
            cap.send(to="x@y.com", subject="hi", body="hello")

    def test_narrow_intersects_recipients(self):
        cap = _make(scope={"to": ["a@b.com", "c@d.com"]})
        narrower = cap.scope(to=["a@b.com", "e@f.com"])
        assert narrower._scope["to"] == ["a@b.com"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/io/test_email_scoping.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

In `src/cogos/io/email/capability.py`:

```python
class EmailCapability(Capability):
    """Send and receive emails. ...existing docstring..."""

    ALL_OPS = {"send", "receive"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result = {}
        # Recipients
        old_to = existing.get("to")
        new_to = requested.get("to")
        if old_to is not None and new_to is not None:
            result["to"] = sorted(set(old_to) & set(new_to))
        elif new_to is not None:
            result["to"] = new_to
        elif old_to is not None:
            result["to"] = old_to

        # Ops
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        result["ops"] = sorted(old_ops & new_ops)
        return result

    def _check(self, op: str, **context) -> None:
        if not self._scope:
            return
        allowed_ops = set(self._scope.get("ops") or self.ALL_OPS)
        if op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not allowed. Allowed: {allowed_ops}")
        to = context.get("to")
        allowed_to = self._scope.get("to")
        if to and allowed_to is not None and to not in allowed_to:
            raise PermissionError(f"Recipient '{to}' not allowed. Allowed: {allowed_to}")

    # Add self._check("send", to=to) at top of send()
    # Add self._check("receive") at top of receive()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/io/test_email_scoping.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/cogos/io/email/capability.py tests/cogos/io/test_email_scoping.py
git commit -m "feat: add scoping to EmailCapability with recipient allowlist"
```

---

### Task 7: SecretsCapability — add scoping

**Files:**
- Modify: `src/cogos/capabilities/secrets.py:32-66`
- Test: `tests/cogos/capabilities/test_secrets_scoping.py`

**Step 1: Write the failing test**

Create `tests/cogos/capabilities/test_secrets_scoping.py`:

```python
"""Tests for SecretsCapability scoping."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.secrets import SecretsCapability


def _make(scope=None):
    repo = MagicMock()
    cap = SecretsCapability(repo, uuid4())
    if scope:
        cap = cap.scope(**scope)
    return cap


class TestSecretsScoping:
    def test_scoped_keys_denies_non_matching(self):
        cap = _make(scope={"keys": ["api-key-*"]})
        with pytest.raises(PermissionError, match="db-password"):
            cap.get("db-password")

    def test_narrow_intersects_patterns(self):
        cap = _make(scope={"keys": ["api-*", "db-*"]})
        narrower = cap.scope(keys=["api-*", "cache-*"])
        assert narrower._scope["keys"] == ["api-*"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/capabilities/test_secrets_scoping.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

In `src/cogos/capabilities/secrets.py`:

```python
import fnmatch

class SecretsCapability(Capability):
    """Secret retrieval. ...existing docstring..."""

    def _narrow(self, existing: dict, requested: dict) -> dict:
        old_keys = existing.get("keys")
        new_keys = requested.get("keys")
        if old_keys is not None and new_keys is not None:
            return {"keys": sorted(set(old_keys) & set(new_keys))}
        if new_keys is not None:
            return {"keys": new_keys}
        if old_keys is not None:
            return {"keys": old_keys}
        return {}

    def _check(self, op: str, **context) -> None:
        if not self._scope:
            return
        patterns = self._scope.get("keys")
        if patterns is None:
            return
        key = context.get("key", "")
        if not any(fnmatch.fnmatch(key, p) for p in patterns):
            raise PermissionError(f"Key '{key}' not allowed. Allowed patterns: {patterns}")

    def get(self, key: str) -> SecretValue | SecretError:
        self._check("get", key=key)
        # ... rest unchanged ...
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/capabilities/test_secrets_scoping.py -v`
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add src/cogos/capabilities/secrets.py tests/cogos/capabilities/test_secrets_scoping.py
git commit -m "feat: add scoping to SecretsCapability with key patterns"
```

---

### Task 8: Replace inline proxies in executor with real capability instances

**Files:**
- Modify: `src/cogos/executor/handler.py:331-417`
- Test: `tests/cogos/test_executor_proxy_replacement.py`

**Step 1: Write the failing test**

Create `tests/cogos/test_executor_proxy_replacement.py`:

```python
"""Tests that _setup_capability_proxies uses real capability classes, not inline proxies."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from cogos.capabilities.events import EventsCapability
from cogos.capabilities.files import FilesCapability
from cogos.capabilities.procs import ProcsCapability
from cogos.db.models import Process, ProcessMode, ProcessStatus
from cogos.executor.handler import _setup_capability_proxies
from cogos.sandbox.executor import VariableTable


def _make_process():
    return Process(
        id=uuid4(),
        name="test-proc",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="lambda",
    )


def _make_repo():
    repo = MagicMock()
    repo.list_process_capabilities.return_value = []
    return repo


class TestSetupCapabilityProxies:
    def test_files_is_real_capability(self):
        vt = VariableTable()
        _setup_capability_proxies(vt, _make_process(), _make_repo())
        files = vt.get("files")
        assert isinstance(files, FilesCapability)

    def test_procs_is_real_capability(self):
        vt = VariableTable()
        _setup_capability_proxies(vt, _make_process(), _make_repo())
        procs = vt.get("procs")
        assert isinstance(procs, ProcsCapability)

    def test_events_is_real_capability(self):
        vt = VariableTable()
        _setup_capability_proxies(vt, _make_process(), _make_repo())
        events = vt.get("events")
        assert isinstance(events, EventsCapability)

    def test_scoped_capability_from_config(self):
        """When ProcessCapability has config, the injected instance should be scoped."""
        repo = _make_repo()
        proc = _make_process()

        # Simulate a ProcessCapability with scope config
        pc = MagicMock()
        pc.capability = uuid4()
        pc.name = "workspace"
        pc.config = {"prefix": "/workspace/", "ops": ["list", "read"]}
        repo.list_process_capabilities.return_value = [pc]

        cap_model = MagicMock()
        cap_model.name = "files"
        cap_model.enabled = True
        cap_model.handler = "cogos.capabilities.files:FilesCapability"
        repo.get_capability.return_value = cap_model

        vt = VariableTable()
        _setup_capability_proxies(vt, proc, repo)

        workspace = vt.get("workspace")
        assert isinstance(workspace, FilesCapability)
        assert workspace._scope == {"prefix": "/workspace/", "ops": ["list", "read"]}
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/test_executor_proxy_replacement.py -v`
Expected: FAIL — `files` is `FilesProxy` not `FilesCapability`

**Step 3: Rewrite `_setup_capability_proxies` in handler.py**

Replace the entire `_setup_capability_proxies` function (lines 331-417) in `src/cogos/executor/handler.py`:

```python
def _setup_capability_proxies(vt: VariableTable, process: Process, repo: Repository, *, run_id: UUID | None = None) -> None:
    """Inject capability instances into the variable table.

    Uses real capability classes (not inline proxies). Applies scope from
    ProcessCapability.config when present.
    """
    import importlib
    import inspect

    from cogos.capabilities.events import EventsCapability
    from cogos.capabilities.files import FilesCapability
    from cogos.capabilities.me import MeCapability
    from cogos.capabilities.procs import ProcsCapability

    # Core capabilities — always available
    vt.set("files", FilesCapability(repo, process.id))
    vt.set("procs", ProcsCapability(repo, process.id))
    vt.set("events", EventsCapability(repo, process.id))
    vt.set("me", MeCapability(repo, process.id, run_id=run_id))
    vt.set("print", print)

    # Dynamically load additional capabilities bound to this process
    pcs = repo.list_process_capabilities(process.id)
    for pc in pcs:
        cap_model = repo.get_capability(pc.capability)
        if cap_model is None or not cap_model.enabled:
            continue

        # Determine namespace — use grant name from ProcessCapability
        ns = pc.name or (cap_model.name.split("/")[0] if "/" in cap_model.name else cap_model.name)

        # Skip core caps that are already set up (unless they have a custom grant name)
        if ns in ("files", "procs", "events", "me") and not pc.config:
            continue

        # Load the handler class
        handler_path = cap_model.handler
        if not handler_path:
            continue
        if ":" in handler_path:
            mod_path, attr_name = handler_path.rsplit(":", 1)
        elif "." in handler_path:
            mod_path, attr_name = handler_path.rsplit(".", 1)
        else:
            continue

        try:
            mod = importlib.import_module(mod_path)
            handler_cls = getattr(mod, attr_name)
            if not inspect.isclass(handler_cls):
                vt.set(ns, handler_cls)
                continue
            instance = handler_cls(repo, process.id)
            # Apply scope from config if present
            if pc.config:
                instance = instance.scope(**pc.config)
            vt.set(ns, instance)
        except (ImportError, AttributeError) as exc:
            logger.warning("Could not load capability %s (%s): %s", cap_model.name, handler_path, exc)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/test_executor_proxy_replacement.py -v`
Expected: All 4 tests PASS

**Step 5: Run existing tests to verify no regressions**

Run: `pytest tests/cogos/ -v --timeout=30`
Expected: All existing tests still pass

**Step 6: Commit**

```bash
git add src/cogos/executor/handler.py tests/cogos/test_executor_proxy_replacement.py
git commit -m "feat: replace inline proxy classes with real capability instances in executor"
```

---

### Task 9: New file-granularity capabilities — FileCapability, FileVersionCapability, DirCapability

**Files:**
- Create: `src/cogos/capabilities/file_cap.py`
- Test: `tests/cogos/capabilities/test_file_caps.py`

**Step 1: Write the failing test**

Create `tests/cogos/capabilities/test_file_caps.py`:

```python
"""Tests for fine-grained file capabilities: FileCapability, FileVersionCapability, DirCapability."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.file_cap import DirCapability, FileCapability, FileVersionCapability


def _make_file(scope=None):
    repo = MagicMock()
    repo.get_active_file_version.return_value = None
    cap = FileCapability(repo, uuid4())
    if scope:
        cap = cap.scope(**scope)
    return cap


def _make_dir(scope=None):
    repo = MagicMock()
    cap = DirCapability(repo, uuid4())
    if scope:
        cap = cap.scope(**scope)
    return cap


class TestFileCapability:
    def test_scoped_key_cannot_change(self):
        cap = _make_file(scope={"key": "/a"})
        with pytest.raises(ValueError, match="Cannot change"):
            cap.scope(key="/b")

    def test_scoped_ops_intersect(self):
        cap = _make_file(scope={"ops": ["read", "write"]})
        narrower = cap.scope(ops=["read", "delete"])
        assert set(narrower._scope["ops"]) == {"read"}

    def test_check_denies_wrong_key(self):
        cap = _make_file(scope={"key": "/config/system"})
        with pytest.raises(PermissionError, match="/other"):
            cap.read("/other/key")

    def test_check_denies_wrong_op(self):
        cap = _make_file(scope={"key": "/a", "ops": ["read"]})
        with pytest.raises(PermissionError, match="write"):
            cap.write("/a", "content")


class TestDirCapability:
    def test_scoped_prefix_cannot_widen(self):
        cap = _make_dir(scope={"prefix": "/config/"})
        with pytest.raises(ValueError, match="Cannot widen"):
            cap.scope(prefix="/other/")

    def test_scoped_prefix_can_narrow(self):
        cap = _make_dir(scope={"prefix": "/config/"})
        narrower = cap.scope(prefix="/config/sub/")
        assert narrower._scope["prefix"] == "/config/sub/"

    def test_check_denies_outside_prefix(self):
        cap = _make_dir(scope={"prefix": "/workspace/"})
        with pytest.raises(PermissionError, match="/secret"):
            cap.read("/secret/file")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/capabilities/test_file_caps.py -v`
Expected: FAIL — module not found

**Step 3: Create `src/cogos/capabilities/file_cap.py`**

```python
"""Fine-grained file capabilities — file, file_version, dir."""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.capabilities.files import FileContent, FileError, FileSearchResult, FileWriteResult
from cogos.files.store import FileStore

logger = logging.getLogger(__name__)


class FileCapability(Capability):
    """Single-file access capability.

    Usage:
        file.read("/config/system")
        file.write("/config/system", "new content")
    """

    ALL_OPS = {"read", "write", "delete", "get_metadata"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        key = requested.get("key") or existing.get("key")
        if existing.get("key") and requested.get("key") and existing["key"] != requested["key"]:
            raise ValueError("Cannot change scoped file key")
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        result = {"ops": sorted(old_ops & new_ops)}
        if key:
            result["key"] = key
        return result

    def _check(self, op: str, **context) -> None:
        if not self._scope:
            return
        allowed = set(self._scope.get("ops") or self.ALL_OPS)
        if op not in allowed:
            raise PermissionError(f"Operation '{op}' not allowed. Allowed: {allowed}")
        scoped_key = self._scope.get("key")
        key = context.get("key", "")
        if scoped_key and key and key != scoped_key:
            raise PermissionError(f"Key '{key}' not allowed. Scoped to: {scoped_key}")

    def read(self, key: str) -> FileContent | FileError:
        if not key:
            return FileError(error="key is required")
        self._check("read", key=key)
        store = FileStore(self.repo)
        f = store.get(key)
        if f is None:
            return FileError(error=f"file '{key}' not found")
        fv = self.repo.get_active_file_version(f.id)
        if fv is None:
            return FileError(error=f"no active version for '{key}'")
        return FileContent(id=str(f.id), key=f.key, version=fv.version, content=fv.content)

    def write(self, key: str, content: str, source: str = "agent") -> FileWriteResult | FileError:
        if not key:
            return FileError(error="key is required")
        self._check("write", key=key)
        store = FileStore(self.repo)
        result = store.upsert(key, content, source=source)
        if result is None:
            return FileWriteResult(id="", key=key, version=0, created=False, changed=False)
        from cogos.db.models import File
        if isinstance(result, File):
            return FileWriteResult(id=str(result.id), key=key, version=1, created=True)
        return FileWriteResult(id=str(result.file_id), key=key, version=result.version, created=False)


class FileVersionCapability(Capability):
    """Single-file version access capability.

    Usage:
        file_version.list("/logs/audit")
        file_version.add("/logs/audit", "new entry")
    """

    ALL_OPS = {"add", "list", "get", "update"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        key = requested.get("key") or existing.get("key")
        if existing.get("key") and requested.get("key") and existing["key"] != requested["key"]:
            raise ValueError("Cannot change scoped file key")
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        result = {"ops": sorted(old_ops & new_ops)}
        if key:
            result["key"] = key
        return result

    def _check(self, op: str, **context) -> None:
        if not self._scope:
            return
        allowed = set(self._scope.get("ops") or self.ALL_OPS)
        if op not in allowed:
            raise PermissionError(f"Operation '{op}' not allowed. Allowed: {allowed}")
        scoped_key = self._scope.get("key")
        key = context.get("key", "")
        if scoped_key and key and key != scoped_key:
            raise PermissionError(f"Key '{key}' not allowed. Scoped to: {scoped_key}")

    def add(self, key: str, content: str, source: str = "agent") -> FileWriteResult | FileError:
        if not key:
            return FileError(error="key is required")
        self._check("add", key=key)
        store = FileStore(self.repo)
        result = store.upsert(key, content, source=source)
        if result is None:
            return FileWriteResult(id="", key=key, version=0, created=False, changed=False)
        from cogos.db.models import File
        if isinstance(result, File):
            return FileWriteResult(id=str(result.id), key=key, version=1, created=True)
        return FileWriteResult(id=str(result.file_id), key=key, version=result.version, created=False)

    def list(self, key: str) -> list[dict]:
        self._check("list", key=key)
        store = FileStore(self.repo)
        f = store.get(key)
        if f is None:
            return []
        versions = self.repo.list_file_versions(f.id)
        return [{"version": v.version, "source": v.source} for v in versions]


class DirCapability(Capability):
    """Directory (prefix) access capability.

    Usage:
        dir.list("/workspace/")
        dir.read("/workspace/notes.md")
        dir.write("/workspace/output.md", "content")
    """

    ALL_OPS = {"list", "read", "write", "create", "delete"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        old_prefix = existing.get("prefix", "/")
        new_prefix = requested.get("prefix", old_prefix)
        if not new_prefix.startswith(old_prefix):
            raise ValueError(f"Cannot widen prefix from {old_prefix} to {new_prefix}")
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        return {"prefix": new_prefix, "ops": sorted(old_ops & new_ops)}

    def _check(self, op: str, **context) -> None:
        if not self._scope:
            return
        allowed = set(self._scope.get("ops") or self.ALL_OPS)
        if op not in allowed:
            raise PermissionError(f"Operation '{op}' not allowed. Allowed: {allowed}")
        prefix = self._scope.get("prefix")
        key = context.get("key", "")
        if prefix and key and not key.startswith(prefix):
            raise PermissionError(f"Key '{key}' outside allowed prefix '{prefix}'")

    def list(self, prefix: str | None = None, limit: int = 50) -> list[FileSearchResult]:
        effective = prefix or self._scope.get("prefix", "")
        self._check("list", key=effective)
        store = FileStore(self.repo)
        files = store.list_files(prefix=effective, limit=limit)
        return [FileSearchResult(id=str(f.id), key=f.key) for f in files]

    def read(self, key: str) -> FileContent | FileError:
        if not key:
            return FileError(error="key is required")
        self._check("read", key=key)
        store = FileStore(self.repo)
        f = store.get(key)
        if f is None:
            return FileError(error=f"file '{key}' not found")
        fv = self.repo.get_active_file_version(f.id)
        if fv is None:
            return FileError(error=f"no active version for '{key}'")
        return FileContent(id=str(f.id), key=f.key, version=fv.version, content=fv.content)

    def write(self, key: str, content: str, source: str = "agent") -> FileWriteResult | FileError:
        if not key:
            return FileError(error="key is required")
        self._check("write", key=key)
        store = FileStore(self.repo)
        result = store.upsert(key, content, source=source)
        if result is None:
            return FileWriteResult(id="", key=key, version=0, created=False, changed=False)
        from cogos.db.models import File
        if isinstance(result, File):
            return FileWriteResult(id=str(result.id), key=key, version=1, created=True)
        return FileWriteResult(id=str(result.file_id), key=key, version=result.version, created=False)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/capabilities/test_file_caps.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add src/cogos/capabilities/file_cap.py tests/cogos/capabilities/test_file_caps.py
git commit -m "feat: add FileCapability, FileVersionCapability, DirCapability for fine-grained file grants"
```

---

### Task 10: Integration test — spawn with scoped capabilities round-trip

**Files:**
- Test: `tests/cogos/capabilities/test_spawn_scoped.py`

**Step 1: Write the integration test**

Create `tests/cogos/capabilities/test_spawn_scoped.py`:

```python
"""Integration test: spawn a child process with scoped capabilities."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from cogos.capabilities.events import EventsCapability
from cogos.capabilities.files import FilesCapability
from cogos.capabilities.procs import ProcsCapability


def test_spawn_with_scoped_capabilities():
    """Verify spawn reads _scope from capability instances and stores as config."""
    repo = MagicMock()
    repo.upsert_process.return_value = uuid4()

    # Set up capability model lookups
    files_cap_model = MagicMock()
    files_cap_model.id = uuid4()
    files_cap_model.enabled = True

    events_cap_model = MagicMock()
    events_cap_model.id = uuid4()
    events_cap_model.enabled = True

    def lookup(name):
        return {"files": files_cap_model, "events": events_cap_model}.get(name)
    repo.get_capability_by_name.side_effect = lookup

    procs = ProcsCapability(repo, uuid4())
    files = FilesCapability(repo, uuid4())
    events = EventsCapability(repo, uuid4())

    # Spawn with scoped capabilities
    result = procs.spawn(
        name="worker",
        content="do work",
        capabilities={
            "workspace": files.scope(prefix="/workspace/", ops=["list", "read"]),
            "events": events,  # unscoped
        },
    )

    assert hasattr(result, "id")

    # Verify ProcessCapability was created with correct config
    calls = repo.create_process_capability.call_args_list
    assert len(calls) == 2

    # Find the workspace grant
    workspace_call = [c for c in calls if c[0][0].name == "workspace"][0]
    pc = workspace_call[0][0]
    assert pc.config == {"prefix": "/workspace/", "ops": ["list", "read"]}

    # Find the events grant — unscoped should have None or empty config
    events_call = [c for c in calls if c[0][0].name == "events"][0]
    pc_events = events_call[0][0]
    assert pc_events.config is None  # empty _scope → stored as None
```

**Step 2: Run test**

Run: `pytest tests/cogos/capabilities/test_spawn_scoped.py -v`
Expected: PASS (this should work with the changes from Tasks 1-4, since `_scope` exists and `spawn()` already reads it via `getattr`)

**Step 3: Commit**

```bash
git add tests/cogos/capabilities/test_spawn_scoped.py
git commit -m "test: integration test for spawn with scoped capabilities"
```

---

### Task 11: Full regression test run

**Step 1: Run all tests**

Run: `pytest tests/ -v --timeout=30`
Expected: All tests PASS

**Step 2: If any fail, fix and commit**

---

## Summary of Changes

| File | Change |
|---|---|
| `src/cogos/capabilities/base.py` | Add `_scope`, `scope()`, `_narrow()`, `_check()` |
| `src/cogos/capabilities/events.py` | Add `_narrow()`, `_check()` with fnmatch patterns |
| `src/cogos/capabilities/procs.py` | Add `_narrow()`, `_check()` with ops |
| `src/cogos/capabilities/files.py` | Add `_narrow()`, `_check()` with prefix + ops |
| `src/cogos/capabilities/secrets.py` | Add `_narrow()`, `_check()` with key patterns |
| `src/cogos/io/discord/capability.py` | Add `_narrow()`, `_check()` with channels + ops |
| `src/cogos/io/email/capability.py` | Add `_narrow()`, `_check()` with recipients + ops |
| `src/cogos/capabilities/file_cap.py` | New: `FileCapability`, `FileVersionCapability`, `DirCapability` |
| `src/cogos/executor/handler.py` | Replace inline proxies with real capability instances |
