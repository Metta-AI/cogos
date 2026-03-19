Pull, merge, test, push, and announce to Discord #cogents.

**Announce at start:** "Submitting: pull → merge → test → push → announce"

## Steps

1. Run `git status` to check for uncommitted changes
   - If there are uncommitted changes, run `/vet` first, then stage and commit with a descriptive message
2. Run `git pull --rebase origin main` to sync with remote
   - If there are merge conflicts, resolve them intelligently, stage, and `git rebase --continue`
3. Run `pytest tests/ -q` to execute unit tests
   - If tests fail, stop and show the failures. Do NOT push broken code. Ask the user how to proceed.
4. Run `git push origin main`
   - If push is rejected, pull --rebase again and retry (max 2 retries)
5. Build a short summary of what was pushed:
   - Use `git log origin/main@{1}..origin/main --oneline` (or similar) to list the commits just pushed
   - Write a 1-3 sentence human-readable summary of the changes
6. Post the summary to Discord #cogents using the webhook:
   ```bash
   WEBHOOK_URL=$(aws secretsmanager get-secret-value --secret-id "discord/channel-webhook/cogents" --query SecretString --output text --profile softmax)
   curl -X POST "$WEBHOOK_URL" -H "Content-Type: application/json" \
     -d "{\"username\": \"cogents.2\", \"content\": \"$SUMMARY\"}"
   ```
   - Keep the message under 2000 characters
   - If the work is tied to an Asana task, include it as a hyperlink: `[Task name](<https://app.asana.com/0/1213428766379931/TASK_GID>)`
   - If the webhook secret doesn't exist, try `discord/agent-webhook-url` as fallback
7. Print the summary locally so the user can see what was announced
