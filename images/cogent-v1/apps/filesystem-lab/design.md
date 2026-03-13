# Filesystem Lab

Reusable prompt assets for testing the local CogOS file store, authored `@{file-key}`
resolution, and the dashboard prompt preview flow.

## What It Covers

- Prompt files that use inline `@{...}` references
- Nested prompt references with deduped shared dependencies
- Legacy `File.includes` wiring via `add_file(...)`
- A sample one-shot process and a sample daemon process you can load locally

## Suggested Local Workflow

1. Boot the image locally.
2. Load `processes.json` to create the test processes.
3. Inspect the prompt preview for `filesystem-lab/respond` in the dashboard.
4. Trigger the daemon through `filesystem-lab:requests`, or run the smoke process directly.
5. Inspect the report file written under `apps/filesystem-lab/output/`.

## Sample Commands

```bash
cogent local cogos image boot cogent-v1 --clean
cogent local cogos process load images/cogent-v1/apps/filesystem-lab/respond.json

cogent local cogos process get filesystem-lab/respond
cogent local cogos file get apps/filesystem-lab/prompts/respond.md

cogent local cogos channel send filesystem-lab:requests \
  --payload '{"task_key": "apps/filesystem-lab/fixtures/sample-task.md", "goal": "verify prompt resolution and file writes"}'

cogent local cogos run-local --once
cogent local cogos file get apps/filesystem-lab/output/latest-report.md

# Optional one-shot smoke test
cogent local cogos process load images/cogent-v1/apps/filesystem-lab/smoke.json
cogent local cogos process run filesystem-lab/smoke --local
```
