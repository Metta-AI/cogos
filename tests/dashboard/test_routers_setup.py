"""Tests for dashboard setup router — gemini secret status and fallback."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


def _make_secrets_provider(secrets: dict[str, str] | None = None):
    """Create a mock SecretsProvider."""
    provider = MagicMock()

    def _get(secret_id):
        if secrets and secret_id in secrets:
            return secrets[secret_id]
        raise KeyError(secret_id)

    provider.get_secret.side_effect = _get
    return provider


def _patch_sp(provider):
    """Patch _get_secrets_provider to return the given provider."""
    return patch("dashboard.routers.setup._get_secrets_provider", return_value=provider)


@pytest.fixture(autouse=True)
def _patch_secrets(monkeypatch):
    """Patch secrets provider so tests don't need AWS."""
    monkeypatch.setenv("COGTAINER", "test-cogtainer")
    mock_sp = MagicMock()
    mock_sp.get_secret.side_effect = KeyError("not mocked")
    with patch("dashboard.routers.setup._get_secrets_provider", return_value=mock_sp), \
         patch("dashboard.routers.setup._get_ecs_client", return_value=None):
        yield


class TestGeminiSecretStatus:
    """Tests for _gemini_secret_status with cogent/all fallback."""

    def test_cogent_specific_secret_found(self):
        from dashboard.routers.setup import _gemini_secret_status

        provider = _make_secrets_provider({
            "cogent/alpha/gemini": json.dumps({"api_key": "key-alpha"}),
        })

        with _patch_sp(provider):
            configured, error, source = _gemini_secret_status("alpha", "us-east-1")

        assert configured is True
        assert error is None
        assert source == "cogent/alpha/gemini"

    def test_falls_back_to_all_secret(self):
        from dashboard.routers.setup import _gemini_secret_status

        provider = _make_secrets_provider({
            "cogtainer/test-cogtainer/gemini": json.dumps({"api_key": "shared-key"}),
        })

        with _patch_sp(provider):
            configured, error, source = _gemini_secret_status("alpha", "us-east-1")

        assert configured is True
        assert error is None
        assert source == "cogtainer/test-cogtainer/gemini"

    def test_cogent_specific_takes_precedence_over_all(self):
        from dashboard.routers.setup import _gemini_secret_status

        provider = _make_secrets_provider({
            "cogent/alpha/gemini": json.dumps({"api_key": "alpha-key"}),
            "cogtainer/test-cogtainer/gemini": json.dumps({"api_key": "shared-key"}),
        })

        with _patch_sp(provider):
            configured, error, source = _gemini_secret_status("alpha", "us-east-1")

        assert configured is True
        assert error is None
        assert source == "cogent/alpha/gemini"

    def test_returns_false_when_both_missing(self):
        from dashboard.routers.setup import _gemini_secret_status

        provider = _make_secrets_provider({})

        with _patch_sp(provider):
            configured, error, source = _gemini_secret_status("alpha", "us-east-1")

        assert configured is False
        assert error is None
        assert source is None

    def test_returns_false_when_api_key_empty(self):
        from dashboard.routers.setup import _gemini_secret_status

        provider = _make_secrets_provider({
            "cogent/alpha/gemini": json.dumps({"api_key": ""}),
            "cogtainer/test-cogtainer/gemini": json.dumps({"api_key": ""}),
        })

        with _patch_sp(provider):
            configured, error, source = _gemini_secret_status("alpha", "us-east-1")

        assert configured is False
        assert error is None
        assert source is None

    def test_returns_error_on_exception(self):
        from dashboard.routers.setup import _gemini_secret_status

        provider = MagicMock()
        provider.get_secret.side_effect = RuntimeError("connection failed")

        with _patch_sp(provider):
            configured, error, source = _gemini_secret_status("alpha", "us-east-1")

        assert configured is None
        assert error == "RuntimeError"
        assert source is None


class TestEmailIntegrationAutoConfig:
    """Tests for EmailIntegration auto-configuration."""

    def test_address_for_derives_from_name(self):
        from cogos.io.integration import EmailIntegration

        assert EmailIntegration.address_for("alpha", "example.com") == "alpha@example.com"
        assert EmailIntegration.address_for("dr.beta", "example.com") == "dr.beta@example.com"

    def test_address_for_empty_domain_returns_empty(self):
        from cogos.io.integration import EmailIntegration

        assert EmailIntegration.address_for("alpha") == ""
        assert EmailIntegration.address_for("alpha", "") == ""

    def test_status_configured_when_domain_available(self):
        from cogos.io.integration import EmailIntegration

        integration = EmailIntegration()
        provider = _make_secrets_provider({"cogtainer/test-cogtainer/email/domain": "example.com"})

        with _patch_sp(provider):
            status = integration.status("alpha", secrets_provider=provider)

        assert status["configured"] is True
        assert status["missing_fields"] == []
        assert status["address"] == "alpha@example.com"

    def test_status_not_configured_when_domain_missing(self):
        from cogos.io.integration import EmailIntegration

        integration = EmailIntegration()
        provider = _make_secrets_provider({})

        with _patch_sp(provider):
            status = integration.status("alpha", secrets_provider=provider)

        assert status["configured"] is False
        assert "domain" in status["missing_fields"]
        assert status["address"] == ""


class TestEmailSesStatus:
    """Tests for _email_ses_status SES domain verification check."""

    def test_domain_verified(self):
        from dashboard.routers.setup import _email_ses_status

        with patch("cogtainer.io.email.provision.ses_domain_status", return_value=(True, None)):
            verified, error = _email_ses_status("example.com", "us-east-1")

        assert verified is True
        assert error is None

    def test_domain_not_verified(self):
        from dashboard.routers.setup import _email_ses_status

        with patch("cogtainer.io.email.provision.ses_domain_status", return_value=(False, None)):
            verified, error = _email_ses_status("example.com", "us-east-1")

        assert verified is False
        assert error is None

    def test_returns_error_on_exception(self):
        from dashboard.routers.setup import _email_ses_status

        with patch("cogtainer.io.email.provision.ses_domain_status", return_value=(None, "RuntimeError")):
            verified, error = _email_ses_status("example.com", "us-east-1")

        assert verified is None
        assert error == "RuntimeError"


def _patch_email_ses(verified, error=None):
    """Patch ses_domain_status for email setup tests."""
    return patch("cogtainer.io.email.provision.ses_domain_status", return_value=(verified, error))


class TestBuildEmailSetup:
    """Tests for _build_email_setup."""

    def test_ready_when_ses_verified_and_capability_enabled(self):
        from dashboard.routers.setup import _build_email_setup

        mock_repo = MagicMock()
        cap = MagicMock()
        cap.name = "email"
        cap.enabled = True
        mock_repo.list_capabilities.return_value = [cap]

        provider = _make_secrets_provider({"cogtainer/test-cogtainer/email/domain": "example.com"})
        with patch("dashboard.routers.setup.get_repo", return_value=mock_repo), \
             _patch_email_ses(True), _patch_sp(provider):
            setup = _build_email_setup("alpha")

        assert setup.status.value == "ready"
        assert setup.ready_for_test is True
        assert "alpha@example.com" in setup.summary

    def test_needs_action_when_ses_not_verified(self):
        from dashboard.routers.setup import _build_email_setup

        mock_repo = MagicMock()
        cap = MagicMock()
        cap.name = "email"
        cap.enabled = True
        mock_repo.list_capabilities.return_value = [cap]

        provider = _make_secrets_provider({"cogtainer/test-cogtainer/email/domain": "example.com"})
        with patch("dashboard.routers.setup.get_repo", return_value=mock_repo), \
             _patch_email_ses(False), _patch_sp(provider):
            setup = _build_email_setup("alpha")

        assert setup.status.value == "needs_action"
        assert setup.ready_for_test is False

    def test_address_step_shows_address_when_domain_configured(self):
        from dashboard.routers.setup import _build_email_setup

        mock_repo = MagicMock()
        mock_repo.list_capabilities.return_value = []

        provider = _make_secrets_provider({"cogtainer/test-cogtainer/email/domain": "example.com"})
        with patch("dashboard.routers.setup.get_repo", return_value=mock_repo), \
             _patch_email_ses(False), _patch_sp(provider):
            setup = _build_email_setup("alpha")

        address_step = setup.steps[0]
        assert address_step.key == "email-address"
        assert address_step.status.value == "ready"
        assert address_step.detail is not None
        assert "alpha@example.com" in address_step.detail


class TestBuildGeminiSetup:
    """Tests for _build_gemini_setup showing shared vs cogent-specific summary."""

    def test_shared_secret_summary(self):
        from dashboard.routers.setup import _build_gemini_setup

        provider = _make_secrets_provider({
            "cogtainer/test-cogtainer/gemini": json.dumps({"api_key": "shared-key"}),
        })

        with _patch_sp(provider):
            setup = _build_gemini_setup("alpha")

        assert "shared" in setup.summary
        assert setup.status.value == "ready"

    def test_cogent_specific_secret_summary(self):
        from dashboard.routers.setup import _build_gemini_setup

        provider = _make_secrets_provider({
            "cogent/alpha/gemini": json.dumps({"api_key": "alpha-key"}),
        })

        with _patch_sp(provider):
            setup = _build_gemini_setup("alpha")

        assert "cogent-specific" in setup.summary
        assert setup.status.value == "ready"

    def test_missing_secret_needs_action(self):
        from dashboard.routers.setup import _build_gemini_setup

        provider = _make_secrets_provider({})

        with _patch_sp(provider):
            setup = _build_gemini_setup("alpha")

        assert setup.status.value == "needs_action"
        assert not setup.ready_for_test
