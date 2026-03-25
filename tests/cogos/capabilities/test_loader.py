"""Tests for the shared capability loader."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from cogos.capabilities.base import Capability
from cogos.capabilities.loader import _resolve_handler, build_capability_proxies


class StubCapability(Capability):
    def _narrow(self, existing, requested):
        return {**existing, **requested}

    def greet(self) -> str:
        return "hello"


class TestResolveHandler:
    def test_dotted_path(self):
        handler = _resolve_handler("cogos.capabilities.base.Capability")
        assert handler is Capability

    def test_colon_path(self):
        handler = _resolve_handler("cogos.capabilities.base:Capability")
        assert handler is Capability

    def test_invalid_module(self):
        handler = _resolve_handler("nonexistent.module.Class")
        assert handler is None

    def test_invalid_attr(self):
        handler = _resolve_handler("cogos.capabilities.base.NonExistent")
        assert handler is None

    def test_bare_name(self):
        handler = _resolve_handler("just_a_name")
        assert handler is None


class TestBuildCapabilityProxies:
    def test_builds_proxies(self):
        repo = MagicMock()
        pid = uuid4()

        # Mock a process capability grant
        pc = MagicMock()
        pc.name = "stub"
        pc.capability = uuid4()
        pc.config = None
        repo.list_process_capabilities.return_value = [pc]

        cap_record = MagicMock()
        cap_record.enabled = True
        cap_record.handler = f"{StubCapability.__module__}.{StubCapability.__name__}"
        cap_record.name = "stub/v1"
        repo.get_capability.return_value = cap_record

        proxies = build_capability_proxies(repo, pid)
        assert "stub" in proxies
        assert isinstance(proxies["stub"], StubCapability)
        assert proxies["stub"].greet() == "hello"

    def test_skips_disabled(self):
        repo = MagicMock()
        pid = uuid4()

        pc = MagicMock()
        pc.name = "stub"
        pc.capability = uuid4()
        pc.config = None
        repo.list_process_capabilities.return_value = [pc]

        cap_record = MagicMock()
        cap_record.enabled = False
        repo.get_capability.return_value = cap_record

        proxies = build_capability_proxies(repo, pid)
        assert "stub" not in proxies

    def test_applies_scope(self):
        repo = MagicMock()
        pid = uuid4()

        pc = MagicMock()
        pc.name = "stub"
        pc.capability = uuid4()
        pc.config = {"table": "users"}
        repo.list_process_capabilities.return_value = [pc]

        cap_record = MagicMock()
        cap_record.enabled = True
        cap_record.handler = f"{StubCapability.__module__}.{StubCapability.__name__}"
        cap_record.name = "stub/v1"
        repo.get_capability.return_value = cap_record

        proxies = build_capability_proxies(repo, pid)
        assert proxies["stub"]._scope == {"table": "users"}  # type: ignore[attr-defined]
