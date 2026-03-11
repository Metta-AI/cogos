import pytest

from polis import aws


@pytest.fixture(autouse=True)
def _reset_profile(monkeypatch):
    previous = aws._profile
    aws.set_profile(None)
    monkeypatch.delenv(aws.ORG_PROFILE_ENV, raising=False)
    yield
    aws.set_profile(previous)


def test_resolve_org_profile_prefers_explicit_value(monkeypatch):
    monkeypatch.setenv(aws.ORG_PROFILE_ENV, "env-profile")

    assert aws.resolve_org_profile("explicit-profile") == "explicit-profile"


def test_resolve_org_profile_uses_env_override(monkeypatch):
    monkeypatch.setenv(aws.ORG_PROFILE_ENV, "env-profile")

    assert aws.resolve_org_profile() == "env-profile"


def test_resolve_org_profile_falls_back_to_repo_default():
    assert aws.resolve_org_profile() == aws.DEFAULT_ORG_PROFILE


def test_set_org_profile_stores_resolved_profile(monkeypatch):
    monkeypatch.setenv(aws.ORG_PROFILE_ENV, "env-profile")

    resolved = aws.set_org_profile()

    assert resolved == "env-profile"
    assert aws._profile == "env-profile"
