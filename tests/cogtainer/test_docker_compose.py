"""Tests for docker-compose.yml generation."""

from __future__ import annotations

import yaml

from cogtainer.config import CogtainerEntry, LLMConfig
from cogtainer.docker_compose import generate_compose


def test_generate_docker_compose_single_cogent():
    entry = CogtainerEntry(
        type="docker",
        data_dir="/tmp/mydata",
        image="cogent:v1",
        llm=LLMConfig(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            api_key_env="ANTHROPIC_API_KEY",
        ),
    )
    result = generate_compose(entry, "mycogtainer", ["agent1"])
    parsed = yaml.safe_load(result)

    assert "services" in parsed
    assert "dispatcher-agent1" in parsed["services"]
    assert "dashboard-agent1" in parsed["services"]

    disp = parsed["services"]["dispatcher-agent1"]
    assert disp["image"] == "cogent:v1"
    assert disp["restart"] == "unless-stopped"
    assert disp["environment"]["COGENT"] == "agent1"
    assert disp["environment"]["COGTAINER"] == "mycogtainer"
    assert disp["environment"]["USE_LOCAL_DB"] == "1"
    assert disp["environment"]["LLM_PROVIDER"] == "anthropic"
    assert disp["environment"]["DEFAULT_MODEL"] == "claude-sonnet-4-20250514"
    assert disp["environment"]["ANTHROPIC_API_KEY"] == "${ANTHROPIC_API_KEY}"
    assert any("/tmp/mydata/agent1:" in v for v in disp["volumes"])

    dash = parsed["services"]["dashboard-agent1"]
    assert "8080:8080" in dash["ports"]
    assert dash["environment"]["COGENT"] == "agent1"


def test_generate_docker_compose_multiple_cogents():
    entry = CogtainerEntry(
        type="docker",
        data_dir="/data/prod",
        llm=LLMConfig(provider="bedrock", model="anthropic.claude-3-sonnet", api_key_env=""),
    )
    result = generate_compose(entry, "prod", ["alpha", "beta"])
    parsed = yaml.safe_load(result)

    assert "dispatcher-alpha" in parsed["services"]
    assert "dispatcher-beta" in parsed["services"]
    assert "dashboard-alpha" in parsed["services"]
    assert "dashboard-beta" in parsed["services"]

    # Ports should be different
    alpha_ports = parsed["services"]["dashboard-alpha"]["ports"]
    beta_ports = parsed["services"]["dashboard-beta"]["ports"]
    assert alpha_ports != beta_ports
    assert "8080:8080" in alpha_ports
    assert "8081:8080" in beta_ports


def test_generate_docker_compose_default_llm():
    entry = CogtainerEntry(
        type="docker", data_dir="/data/dev",
        llm=LLMConfig(provider="bedrock", model="test-model", api_key_env=""),
    )
    result = generate_compose(entry, "dev", ["bot"])
    parsed = yaml.safe_load(result)

    disp = parsed["services"]["dispatcher-bot"]
    assert disp["environment"]["LLM_PROVIDER"] == "bedrock"
    assert disp["environment"]["DEFAULT_MODEL"] == "test-model"


def test_generate_docker_compose_default_image():
    entry = CogtainerEntry(type="docker", llm=LLMConfig(provider="bedrock", model="test-model", api_key_env=""))
    result = generate_compose(entry, "test", ["x"])
    parsed = yaml.safe_load(result)

    assert parsed["services"]["dispatcher-x"]["image"] == "cogent:latest"
    assert parsed["services"]["dashboard-x"]["image"] == "cogent:latest"


def test_generate_docker_compose_valid_yaml():
    entry = CogtainerEntry(
        type="docker",
        data_dir="/tmp/test",
        llm=LLMConfig(provider="anthropic", model="claude-sonnet-4-20250514", api_key_env="KEY"),
    )
    result = generate_compose(entry, "c1", ["a", "b"])
    # Should be valid YAML
    parsed = yaml.safe_load(result)
    assert parsed["version"] == "3.8"
    assert len(parsed["services"]) == 4  # 2 cogents * 2 services each
