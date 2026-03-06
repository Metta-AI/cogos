Commit all changes, sync with remote, and push to main.

## Steps

1. Run `git status` to see what's changed
2. If there are uncommitted changes:
   - Stage all modified and untracked files (except sensitive files like .env)
   - Create a commit with a descriptive message summarizing the changes
3. Run `git pull --rebase origin main` to sync with remote
4. If there are merge conflicts:
   - Read each conflicted file
   - Resolve conflicts intelligently (keep both sides where appropriate, prefer our changes for intentional modifications)
   - Stage resolved files and `git rebase --continue`
5. Run `git push origin main`
6. If push is rejected, pull --rebase again and retry push (max 2 retries)
7. Run `/clear` to reset conversation context
