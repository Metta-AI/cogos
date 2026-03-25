"""Tests for mount-based file prefix mapping."""
import subprocess

from cogos.image.spec import load_image


def test_app_files_written_under_mnt_boot(tmp_path):
    """App files should be keyed under mnt/boot/ instead of apps/."""
    app_dir = tmp_path / "apps" / "myapp"
    app_dir.mkdir(parents=True)
    (app_dir / "main.py").write_text("print('hello')")

    spec = load_image(tmp_path)
    assert "mnt/boot/myapp/main.py" in spec.files
    assert "apps/myapp/main.py" not in spec.files


def test_non_app_files_written_under_mnt_boot(tmp_path):
    """Non-app content dirs (cogos/, includes/) should also go under mnt/boot/."""
    inc_dir = tmp_path / "includes"
    inc_dir.mkdir()
    (inc_dir / "prompt.md").write_text("# Prompt")

    spec = load_image(tmp_path)
    assert "mnt/boot/includes/prompt.md" in spec.files
    assert "includes/prompt.md" not in spec.files


def test_repo_files_written_under_mnt_repo(tmp_path):
    """Git repo contents should be copied under mnt/repo/."""
    # Create a minimal git repo
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "commit.gpgsign", "false"],
        check=True, capture_output=True,
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / "README.md").write_text("# Hello")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"],
        check=True, capture_output=True,
    )

    spec = load_image(tmp_path)
    assert "mnt/repo/src/main.py" in spec.files
    assert "mnt/repo/README.md" in spec.files
