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
10. Run `/clear` to reset conversation context
