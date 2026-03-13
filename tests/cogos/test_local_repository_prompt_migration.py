import json
from uuid import uuid4

from cogos.db.local_repository import LocalRepository


def test_local_repository_migrates_legacy_prompt_roots_into_content(tmp_path):
    process_id = uuid4()
    file_id = uuid4()

    (tmp_path / "cogos_data.json").write_text(json.dumps({
        "processes": [
            {
                "id": str(process_id),
                "name": "worker",
                "mode": "one_shot",
                "content": "Body instructions",
                "files": [str(file_id)],
            }
        ],
        "files": [
            {
                "id": str(file_id),
                "key": "prompts/worker.md",
                "includes": [],
            }
        ],
    }))

    repo = LocalRepository(str(tmp_path))
    process = repo.get_process(process_id)

    assert process is not None
    assert process.content == "@{prompts/worker.md}\n\nBody instructions"
