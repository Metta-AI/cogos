from pathlib import Path
import json

from cogos.image.spec import load_image


def test_cogent_v1_filesystem_lab_files_load():
    spec = load_image(Path("images/cogent-v1"))
    keys = {key for key in spec.files if key.startswith("apps/filesystem-lab/")}

    assert "apps/filesystem-lab/prompts/respond.md" in keys
    assert "apps/filesystem-lab/prompts/smoke.md" in keys
    assert "apps/filesystem-lab/whoami.md" in keys
    assert "apps/filesystem-lab/fixtures/sample-task.md" in keys
    assert "apps/filesystem-lab/playbooks/operating-rules.md" in keys
    assert "apps/filesystem-lab/playbooks/report-format.md" in keys
    assert "apps/filesystem-lab/playbooks/shared-style.md" in keys


def test_cogent_v1_filesystem_lab_prompt_includes():
    spec = load_image(Path("images/cogent-v1"))

    assert spec.file_includes["apps/filesystem-lab/prompts/respond.md"] == [
        "apps/filesystem-lab/whoami.md",
    ]
    assert spec.file_includes["apps/filesystem-lab/prompts/smoke.md"] == [
        "apps/filesystem-lab/whoami.md",
    ]

    respond_prompt = spec.files["apps/filesystem-lab/prompts/respond.md"]
    assert "@{apps/filesystem-lab/playbooks/operating-rules.md}" in respond_prompt
    assert "@{apps/filesystem-lab/playbooks/report-format.md}" in respond_prompt

    operating_rules = spec.files["apps/filesystem-lab/playbooks/operating-rules.md"]
    report_format = spec.files["apps/filesystem-lab/playbooks/report-format.md"]
    assert "@{apps/filesystem-lab/playbooks/shared-style.md}" in operating_rules
    assert "@{apps/filesystem-lab/playbooks/shared-style.md}" in report_format


def test_filesystem_lab_process_templates_exist():
    process_defs_path = Path("images/cogent-v1/apps/filesystem-lab/processes.json")
    entries = json.loads(process_defs_path.read_text())

    names = {entry["name"] for entry in entries}
    assert names == {"filesystem-lab/respond", "filesystem-lab/smoke"}

    respond = next(entry for entry in entries if entry["name"] == "filesystem-lab/respond")
    assert respond["code_key"] == "apps/filesystem-lab/prompts/respond.md"
    assert respond["handlers"] == ["filesystem-lab:requests"]
    assert respond["capabilities"] == ["dir", "me"]

    smoke = next(entry for entry in entries if entry["name"] == "filesystem-lab/smoke")
    assert smoke["code_key"] == "apps/filesystem-lab/prompts/smoke.md"
    assert smoke["handlers"] == []

    respond_only = json.loads(Path("images/cogent-v1/apps/filesystem-lab/respond.json").read_text())
    smoke_only = json.loads(Path("images/cogent-v1/apps/filesystem-lab/smoke.json").read_text())
    assert respond_only[0]["name"] == "filesystem-lab/respond"
    assert smoke_only[0]["name"] == "filesystem-lab/smoke"
