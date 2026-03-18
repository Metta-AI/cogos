"""Tests for diagnostics cog loading and structure."""

from pathlib import Path

from cogos.cog.cog import Cog


DIAGNOSTICS_DIR = Path(__file__).parent.parent.parent / "images" / "cogent-v1" / "apps" / "diagnostics"


class TestDiagnosticsCog:
    def test_cog_loads(self):
        cog = Cog(DIAGNOSTICS_DIR)
        assert cog.name == "diagnostics"
        assert cog.config.mode == "one_shot"
        assert cog.config.executor == "python"
        assert cog.main_entrypoint == "main.py"

    def test_has_diagnostic_subdirs(self):
        expected_dirs = {
            "files", "channels", "procs", "me", "scheduler", "stdlib",
            "discord", "web", "blob", "image", "email", "asana",
            "github", "alerts", "includes",
        }
        actual_dirs = {
            d.name for d in DIAGNOSTICS_DIR.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        }
        missing = expected_dirs - actual_dirs
        assert not missing, f"Missing diagnostic directories: {missing}"

    def test_each_category_has_diagnostics(self):
        for subdir in DIAGNOSTICS_DIR.iterdir():
            if not subdir.is_dir() or subdir.name.startswith("."):
                continue
            files = list(subdir.rglob("*.py")) + list(subdir.rglob("*.md"))
            assert len(files) > 0, f"No diagnostics in {subdir.name}/"

    def test_md_diagnostics_have_verify_block(self):
        for md_file in DIAGNOSTICS_DIR.rglob("*.md"):
            content = md_file.read_text()
            assert "```python verify" in content, (
                f"{md_file.relative_to(DIAGNOSTICS_DIR)} missing ```python verify block"
            )

    def test_py_diagnostics_have_valid_syntax(self):
        import ast
        for py_file in DIAGNOSTICS_DIR.rglob("*.py"):
            if py_file.name in ("cog.py", "main.py"):
                continue
            try:
                ast.parse(py_file.read_text())
            except SyntaxError as e:
                raise AssertionError(
                    f"Syntax error in {py_file.relative_to(DIAGNOSTICS_DIR)}: {e}"
                )

    def test_main_py_has_valid_syntax(self):
        import ast
        main = DIAGNOSTICS_DIR / "main.py"
        ast.parse(main.read_text())

    def test_caps_covers_all_dirs(self):
        """Verify that every subdirectory has an entry in _CAPS."""
        import re
        main_content = (DIAGNOSTICS_DIR / "main.py").read_text()
        # Extract all keys from _CAPS dict
        caps_keys = set(re.findall(r'"([^"]+)":\s*\{', main_content))

        for subdir in DIAGNOSTICS_DIR.iterdir():
            if not subdir.is_dir() or subdir.name.startswith("."):
                continue
            # Only check dirs that contain .py diagnostics (runner skips .md)
            py_files = list(subdir.rglob("*.py"))
            if not py_files:
                continue
            name = subdir.name
            has_entry = name in caps_keys or any(
                k.startswith(name + "/") for k in caps_keys
            )
            assert has_entry, (
                f"Directory {name}/ has no entry in _CAPS"
            )
