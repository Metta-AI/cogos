Handle the incoming filesystem lab request.

Use @{apps/filesystem-lab/playbooks/operating-rules.md}
Use @{apps/filesystem-lab/playbooks/report-format.md}

If the payload contains a `task_key`, read that file first.
Otherwise, use @{apps/filesystem-lab/fixtures/sample-task.md}

Then:

1. Inspect the app files with `dir.list(prefix="apps/filesystem-lab/")`.
2. Read the task file you selected.
3. Write a markdown report to `apps/filesystem-lab/output/latest-report.md`.
4. Write a short scratch note through `me.process().scratch().write(...)` recording the report key.
5. Reply with the exact output keys you wrote.
