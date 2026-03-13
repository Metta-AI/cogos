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
    assert fibonacci["capabilities"] == ["dir"]
    assert fibonacci["handlers"] == ["fibonacci:poke"]
    assert fibonacci["metadata"] == {"session": {"mode": "process"}}


def test_cogent_v1_fibonacci_files_and_prompt():
    spec = load_image(Path("images/cogent-v1"))
    fibonacci_files = {k for k in spec.files if k.startswith("apps/fibonacci/")}

    assert fibonacci_files == {"apps/fibonacci/prompts/fibonacci.md"}
    prompt = spec.files["apps/fibonacci/prompts/fibonacci.md"]
    assert "fibonacci:poke" in prompt
    assert "If this is the first time, reply with `0`." in prompt
    assert "look back at the prior conversation in this session" in prompt
    assert "Reply with only the next Fibonacci number." in prompt


def test_cogent_v1_fibonacci_channels():
    spec = load_image(Path("images/cogent-v1"))

    channel_names = {c["name"] for c in spec.channels}
    assert "fibonacci:poke" in channel_names
    assert "fibonacci:steps" not in channel_names
