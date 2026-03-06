Commit all changes, sync with remote, and push to main.

## Steps

1. Run `git status` to see what's changed
2. If there are uncommitted changes, run `/vet` to check for issues before committing
3. If vet finds real issues in our changes (not other sessions), fix them first
4. Stage all modified and untracked files (except sensitive files like .env)
5. Create a commit with a descriptive message summarizing the changes
6. Run `git pull --rebase origin main` to sync with remote
7. If there are merge conflicts:
   - Read each conflicted file
   - Resolve conflicts intelligently (keep both sides where appropriate, prefer our changes for intentional modifications)
   - Stage resolved files and `git rebase --continue`
8. Run `git push origin main`
9. If push is rejected, pull --rebase again and retry push (max 2 retries)
10. Print a session summary:
    - List the key things accomplished (commits made, features added, bugs fixed, deployments done)
    - Keep it concise — bullet points, not paragraphs
11. Rename the conversation to a short descriptive title reflecting what was done (e.g. "Fix polis status + dashboard deploy")
12. Reset the cmux workspace name by running: `cmux rename-workspace "cwd -- cogents.3"`
13. Use the AskUserQuestion tool to ask: "Press Enter to clear, or type 'n' to keep working"
    - If the response is empty or anything other than "n"/"no": run `/clear`
    - If the response is "n" or "no": stop and let the user continue working

