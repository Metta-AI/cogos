"""Tests for build_process_capabilities — extracts capability loading from _setup_capability_proxies."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def process_id():
    return uuid4()


class TestBuildProcessCapabilities:
    def test_returns_empty_dict_when_no_bindings(self, repo, process_id):
        repo.list_process_capabilities.return_value = []
        from cogos.executor.capabilities import build_process_capabilities

        result = build_process_capabilities(process_id, repo)
        assert result == {}

    def test_loads_capability_and_applies_scope(self, repo, process_id):
        pc = MagicMock()
        pc.name = "mem"
        pc.capability = uuid4()
        pc.config = {"keys": ["test/*"]}

        cap_model = MagicMock()
        cap_model.name = "memory"
        cap_model.handler = "cogos.capabilities.secrets:SecretsCapability"
        cap_model.enabled = True

        repo.list_process_capabilities.return_value = [pc]
        repo.get_capability.return_value = cap_model

        with patch("cogos.executor.capabilities.importlib") as mock_importlib:
            mock_cls = MagicMock()
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_scoped = MagicMock()
            mock_instance.scope.return_value = mock_scoped

            mock_mod = MagicMock()
            setattr(mock_mod, "SecretsCapability", mock_cls)
            mock_importlib.import_module.return_value = mock_mod

            from cogos.executor.capabilities import build_process_capabilities

            result = build_process_capabilities(process_id, repo)

        assert "mem" in result
        mock_instance.scope.assert_called_once_with(keys=["test/*"])

    def test_skips_disabled_capabilities(self, repo, process_id):
        pc = MagicMock()
        pc.name = "mem"
        pc.capability = uuid4()
        pc.config = None

        cap_model = MagicMock()
        cap_model.enabled = False

        repo.list_process_capabilities.return_value = [pc]
        repo.get_capability.return_value = cap_model

        from cogos.executor.capabilities import build_process_capabilities

        result = build_process_capabilities(process_id, repo)
        assert result == {}
