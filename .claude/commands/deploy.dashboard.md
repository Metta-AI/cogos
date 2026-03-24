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
| `dashboard/frontend/**` only | Deploy new dashboard image (CI builds on push to main) |
| `src/dashboard/**` only (backend API) | Deploy new dashboard image (CI builds on push to main) |
| Both frontend + backend | Deploy new dashboard image (CI builds on push to main) |
| No dashboard changes | Nothing to deploy. Tell the user. |

## Deploy

CI (GitHub Actions) builds a new dashboard image on push to main. Once the image is available in ECR, deploy it:

```bash
# Deploy a specific build (use the commit SHA from the merged PR)
cogtainer update <cogtainer-name> --services --image-tag dashboard-<sha>

# Deploy the latest image
cogtainer update <cogtainer-name> --services --image-tag dashboard-latest
```

## Post-deploy

After deploy completes, verify by opening `https://<safe-name>.softmax-cogents.com` in the browser and confirm the change is visible.
