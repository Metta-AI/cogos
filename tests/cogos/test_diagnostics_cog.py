"""Tests for diagnostics cog loading and structure."""

from pathlib import Path

from cogos.cog.cog import Cog


DIAGNOSTICS_DIR = Path(__file__).parent.parent.parent / "images" / "cogos" / "apps" / "diagnostics"


class TestDiagnosticsCog:
    def test_cog_loads(self):
        cog = Cog(DIAGNOSTICS_DIR)
        assert cog.name == "diagnostics"
        assert cog.config.mode in ("one_shot", "daemon")
        assert cog.config.executor == "python"
        assert cog.main_entrypoint == "main.py"

    def test_has_diagnostic_subdirs(self):
        expected_dirs = {
            "files", "channels", "spawn", "me", "scheduler",
            "discord", "web", "blob", "image", "email", "asana",
            "github", "alerts", "includes", "stdlib", "history",
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

    def test_diag_files_have_valid_syntax(self):
        import ast
        for py_file in DIAGNOSTICS_DIR.rglob("diag.py"):
            try:
                ast.parse(py_file.read_text())
            except SyntaxError as e:
                raise AssertionError(
                    f"Syntax error in {py_file.relative_to(DIAGNOSTICS_DIR)}: {e}"
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

    def test_all_categories_in_main(self):
        """Verify CATEGORIES dict covers key categories."""
        import re
        main_content = (DIAGNOSTICS_DIR / "main.py").read_text()
        cat_keys = set(re.findall(r'"(\w+)":\s*\(', main_content))
        expected = {"files", "channels", "spawn", "me", "builtins", "history"}
        missing = expected - cat_keys
        assert not missing, f"Missing categories: {missing}"
