"""Tests for the task file loader."""

import textwrap
from pathlib import Path

from brain.db.models import TaskStatus
from mind.task_loader import load_tasks_from_dir


def test_load_markdown_simple(tmp_path: Path):
    """A plain .md file becomes a task with do-content program."""
    (tmp_path / "check-stuff.md").write_text("Do the thing.")
    tasks = load_tasks_from_dir(tmp_path)
    assert len(tasks) == 1
    t = tasks[0]
    assert t.name == "check-stuff"
    assert t.program_name == "do-content"
    assert t.content == "Do the thing."
    assert t.status == TaskStatus.RUNNABLE


def test_load_markdown_with_frontmatter(tmp_path: Path):
    """Frontmatter overrides defaults."""
    (tmp_path / "review.md").write_text(textwrap.dedent("""\
        ---
        priority: 5.0
        runner: ecs
        memory_keys: ["/repo/context"]
        ---
        Review open PRs.
    """))
    tasks = load_tasks_from_dir(tmp_path)
    assert len(tasks) == 1
    t = tasks[0]
    assert t.priority == 5.0
    assert t.runner == "ecs"
    assert t.memory_keys == ["/repo/context"]
    assert t.content == "Review open PRs."


def test_load_markdown_subdirectory(tmp_path: Path):
    """Subdirectory paths become task name prefixes."""
    sub = tmp_path / "reviews"
    sub.mkdir()
    (sub / "daily.md").write_text("Check PRs.\n")
    tasks = load_tasks_from_dir(tmp_path)
    assert tasks[0].name == "reviews/daily"


def test_load_yaml_single(tmp_path: Path):
    """A YAML file with a single task object."""
    (tmp_path / "task.yaml").write_text(textwrap.dedent("""\
        name: deploy-check
        program_name: do-content
        content: Check deployments
        priority: 3.0
    """))
    tasks = load_tasks_from_dir(tmp_path)
    assert len(tasks) == 1
    assert tasks[0].name == "deploy-check"
    assert tasks[0].priority == 3.0


def test_load_yaml_multiple(tmp_path: Path):
    """A YAML file with a tasks list."""
    (tmp_path / "tasks.yml").write_text(textwrap.dedent("""\
        tasks:
          - name: task-a
            content: Do A
          - name: task-b
            content: Do B
            priority: 2.0
    """))
    tasks = load_tasks_from_dir(tmp_path)
    assert len(tasks) == 2
    assert tasks[0].name == "task-a"
    assert tasks[1].name == "task-b"
    assert tasks[1].priority == 2.0


def test_load_disabled_task(tmp_path: Path):
    """A disabled task gets DISABLED status."""
    (tmp_path / "off.md").write_text(textwrap.dedent("""\
        ---
        disabled: true
        ---
        This task is off.
    """))
    tasks = load_tasks_from_dir(tmp_path)
    assert tasks[0].status == TaskStatus.DISABLED


def test_load_empty_dir(tmp_path: Path):
    """Empty directory returns no tasks."""
    assert load_tasks_from_dir(tmp_path) == []


def test_load_nonexistent_dir(tmp_path: Path):
    """Non-existent directory returns no tasks."""
    assert load_tasks_from_dir(tmp_path / "nope") == []
