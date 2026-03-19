Create a Graphite PR with auto-merge, test, and announce to Discord #cogents.

**Announce at start:** "Submitting via Graphite: sync → branch → test → submit → announce"

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
6. Build a short summary of what was submitted:
   - Use `gt log` or `git log main..HEAD --oneline` to list the commits in the PR
   - Include the PR URL from the `gt submit` output
   - Write a 1-3 sentence human-readable summary of the changes
7. Post the summary to Discord #cogents using the webhook:
   ```bash
   WEBHOOK_URL=$(aws secretsmanager get-secret-value --secret-id "discord/channel-webhook/cogents" --query SecretString --output text --profile softmax)
   curl -X POST "$WEBHOOK_URL" -H "Content-Type: application/json" \
     -d "{\"username\": \"cogents.2\", \"content\": \"$SUMMARY\"}"
   ```
   - Keep the message under 2000 characters
   - Include the PR link in the Discord message
   - If the webhook secret doesn't exist, try `discord/agent-webhook-url` as fallback
8. Print the summary locally so the user can see what was announced
