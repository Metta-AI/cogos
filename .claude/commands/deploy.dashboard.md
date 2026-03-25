Deploy dashboard changes with minimal disruption.

Human-readable reference: [docs/deploy.md](../../docs/deploy.md)

## Pre-flight

1. Ensure no uncommitted changes: `git status --porcelain` must be empty. If dirty, stop and ask.
2. Pull latest: `git pull --ff-only`. If it fails (diverged), stop and ask.
3. Ensure the right cogent is selected: check `.env` for COGTAINER/COGENT, or run `cogent select <name>` to set them.

## Decide what to deploy

Run `git diff HEAD~1 --name-only` (or broader if multiple commits since last deploy) and categorize:

| Changed paths | What's needed |
|---|---|
| `dashboard/frontend/**` or `src/dashboard/**` | Dashboard deploy needed |
| No dashboard changes | Nothing to deploy. Tell the user. |

## Deploy

```bash
# Deploy dashboard (resolves version from versions.defaults.json)
cogent update dashboard

# Deploy specific SHA
cogent update dashboard --sha <sha>
```

Dashboard ECR tags use `sha-{sha}` format in the `cogent-dashboard` repo.

## Post-deploy

After deploy completes, verify by opening `https://<safe-cogent-name>.softmax-cogents.com` in the browser and confirm the change is visible.
