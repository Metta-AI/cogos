"""Tests for the fibonacci demo app image."""

from pathlib import Path

from cogos.image.spec import load_image


def test_cogent_v1_fibonacci_loads():
    spec = load_image(Path("images/cogent-v1"))

    proc_names = {p["name"] for p in spec.processes}
    assert "fibonacci" in proc_names

    fibonacci = next(p for p in spec.processes if p["name"] == "fibonacci")
    assert fibonacci["mode"] == "daemon"
    assert fibonacci["content"] == "@{apps/fibonacci/prompts/fibonacci.md}"
    assert fibonacci["capabilities"] == ["channels", "dir"]
    assert fibonacci["handlers"] == ["fibonacci:poke"]
    assert fibonacci["metadata"] == {"session": {"mode": "process"}}


def test_cogent_v1_fibonacci_files_and_prompt():
    spec = load_image(Path("images/cogent-v1"))
    fibonacci_files = {k for k in spec.files if k.startswith("apps/fibonacci/")}

    assert fibonacci_files == {"apps/fibonacci/prompts/fibonacci.md"}
    prompt = spec.files["apps/fibonacci/prompts/fibonacci.md"]
    assert "fibonacci:poke" in prompt
    assert 'channels.send("fibonacci:steps"' in prompt
    assert "process-scoped session resume" in prompt
    assert "Do not store Fibonacci state in the process filesystem." in prompt


def test_cogent_v1_fibonacci_channels_and_schema():
    spec = load_image(Path("images/cogent-v1"))

    channel_names = {c["name"] for c in spec.channels}
    assert "fibonacci:poke" in channel_names
    assert "fibonacci:steps" in channel_names

    schema_names = {s["name"] for s in spec.schemas}
    assert "fibonacci-step" in schema_names
