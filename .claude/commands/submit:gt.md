Create a Graphite PR with auto-merge, wait for it to land, and announce to Discord #cogents.

**Announce at start:** "Submitting via Graphite: sync → branch → test → submit → await merge → announce"

## Steps

1. Run `git status` to check for uncommitted changes
   - If there are uncommitted changes, run `/vet` first, then stage and commit with a descriptive message
2. Run `gt sync -f` to sync with remote and clean up merged branches
3. If not already on a feature branch (i.e. on `main`), create one:
   - Run `gt create -a -m "<short description of changes>"` to create a new Graphite branch with all changes
   - If already on a non-main branch, just ensure changes are committed
4. Run `pytest tests/ -q` to execute unit tests
   - If tests fail, stop and show the failures. Do NOT submit broken code. Ask the user how to proceed.
5. Run `gt submit -m` to push the branch and create a PR with auto-merge enabled
   - If submit fails, check `gt status` and resolve issues
6. **Wait for the PR to merge.** Poll with `gh pr view <number> --json state,mergeStateStatus,mergeable,statusCheckRollup` every 30 seconds.
   - If CI checks fail: read the failing check logs with `gh run view`, diagnose the issue, fix it, commit, and `gt submit -m` again
   - If there are merge conflicts: rebase onto main (`gt sync -f`, resolve conflicts, `gt submit -m`)
   - If the PR is stuck (not progressing after 5 minutes), investigate and report to the user
   - Once `state` is `MERGED`, continue to the next step
7. Run `gt sync -f` to pull the merged changes back to local main
8. Build a short summary of what was merged:
   - Write a 1-3 sentence human-readable summary of the changes
9. Post the summary to Discord #cogents using the webhook:
   ```bash
   WEBHOOK_URL=$(aws secretsmanager get-secret-value --secret-id "discord/channel-webhook/cogents" --query SecretString --output text --profile softmax)
   curl -X POST "$WEBHOOK_URL" -H "Content-Type: application/json" \
     -d "{\"username\": \"cogents.2\", \"content\": \"$SUMMARY\"}"
   ```
   - Keep the message under 2000 characters
   - Include the PR as a markdown hyperlink: `[PR #123](<https://github.com/...>)` — angle brackets suppress Discord's embed preview
   - If the work is tied to an Asana task, include it as a hyperlink too: `[Task name](<https://app.asana.com/0/1213428766379931/TASK_GID>)`
   - If the webhook secret doesn't exist, try `discord/agent-webhook-url` as fallback
10. Print the summary locally so the user can see what was announced
