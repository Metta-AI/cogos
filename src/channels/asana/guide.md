# Asana Personal Access Token Setup

1. Go to https://app.asana.com/0/my-apps
2. Click 'Create new token'
3. Give it a descriptive name (e.g. 'cogent-dr-alpha')
4. Copy the token (you won't be able to see it again)

The token gives access to all workspaces the creating user belongs to.
For workspace/project filtering, set env vars on the cogent:

    ASANA_WORKSPACE_ID   — limit polling to one workspace
    ASANA_ASSIGNEE_GID   — Asana user GID for this cogent
    ASANA_PROJECT_GIDS   — comma-separated project GIDs to watch
