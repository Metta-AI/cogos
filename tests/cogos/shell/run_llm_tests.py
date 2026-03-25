"""Manual test script for llm shell command — run with: uv run --extra dev python tests/cogos/shell/run_llm_tests.py"""

import os
import time

os.environ["COGENT_ID"] = "local"
os.environ["USE_LOCAL_DB"] = "1"

from cli.local_dev import apply_local_checkout_env

apply_local_checkout_env()

from cogos.db.factory import create_repository  # noqa: E402
from cogos.shell.commands import ShellState  # noqa: E402
from cogos.shell.commands.llm import _execute_prompt  # noqa: E402
from cogtainer.config import load_config  # noqa: E402
from cogtainer.runtime.factory import create_runtime  # noqa: E402

repo = create_repository()
cogtainer_name = os.environ.get("COGTAINER", "dev")
cfg = load_config()
entry = cfg.cogtainers[cogtainer_name]
runtime = create_runtime(entry, cogtainer_name)
state = ShellState(cogent_name="local", repo=repo, cwd="", runtime=runtime)

tests = [
    ("print hello world", "simple print"),
    ("what is 2+2?", "simple math"),
    ("list all files under apps/", "file listing"),
    ("read apps/fibonacci/fibonacci.md and summarize in one sentence", "file read"),
    ("create file data/test2.md with 'hello from shell test'", "file write"),
    ("list all processes", "process listing"),
]

for prompt, label in tests:
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"PROMPT: {prompt}")
    print(f"{'='*60}")
    start = time.time()
    result = _execute_prompt(state, prompt, verbose=True)
    elapsed = time.time() - start
    print(f"\n--- returned in {elapsed:.1f}s ---")
    print(result)
