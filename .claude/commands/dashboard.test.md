Test a deployed dashboard using PAT to verify UI and API match the current branch.

## Steps

### 1. Get credentials

```bash
cogent <name> dashboard show-pat
```

This prints the PAT. Also fetch the CF service token:

```python
from polis.aws import get_polis_session, set_profile
import json
set_profile('!`.venv/bin/python scripts/deploy-config org_profile softmax-org`')
session, _ = get_polis_session()
sm = session.client('secretsmanager', region_name='us-east-1')
cf_token = json.loads(sm.get_secret_value(SecretId="cogent/polis/cloudflare-service-token")["SecretString"])
api_key = json.loads(sm.get_secret_value(SecretId=f"cogent/<name>/dashboard-api-key")["SecretString"])["api_key"]
```

### 2. Identify what to verify

Run `git log --oneline -10 -- dashboard/ src/dashboard/` to find recent meaningful dashboard changes. For each change, determine a concrete verification:

| Change type | How to verify |
|---|---|
| Frontend component change | Screenshot the relevant tab/section with agent-browser |
| API endpoint change | `curl` the endpoint and check response shape |
| New feature/tab | Navigate to it and snapshot |
| Bug fix | Reproduce the original bug scenario, confirm it's fixed |
| Header/layout change | Screenshot the header area |

### 3. Test API health

Use curl with CF service token headers to bypass Cloudflare Access:

```bash
curl -s -H "CF-Access-Client-Id: <client_id>" \
     -H "CF-Access-Client-Secret: <client_secret>" \
     "https://<safe-name>.!`.venv/bin/python scripts/deploy-config domain softmax-cogents.com`/api/cogents/<name>/cogos-status"
```

Verify:
- HTTP 200
- Response contains expected fields (`processes`, `capabilities`, `scheduler_last_tick`)

Also test:
- `/healthz` returns `{"ok": true}`
- `/api/cogents/<name>/processes` returns process list
- `/api/cogents/<name>/events` returns events

### 4. Test UI with agent-browser

Use agent-browser with the PAT query param to bypass Cloudflare Access:

```bash
agent-browser open "https://<safe-name>.softmax-cogents.com/?pat=<api_key>"
agent-browser wait --load networkidle
agent-browser screenshot /tmp/dashboard-test.png
```

If Cloudflare blocks the PAT query param, use the CF service token via curl to get a `CF_Authorization` cookie, then load that state into the browser session.

Verify:
- Page loads (not 502, not CF login wall)
- Header shows cogent name and tick indicator
- Processes tab shows expected processes
- Navigate to each relevant tab changed in recent commits and screenshot

### 5. Compare against branch

For each recent dashboard change identified in step 2:
- Confirm the change is visible in the live dashboard
- If a component was added, verify it renders
- If text/labels changed, verify the new text appears
- If an API endpoint was added, verify it responds

### 6. Report

Print a summary:

```
## Dashboard Test Results — <name>

| Check | Status | Detail |
|---|---|---|
| API /healthz | ✓ | 200 OK |
| API /cogos-status | ✓ | 2 processes, tick 30s ago |
| UI loads | ✓ | No errors |
| <specific change> | ✓/✗ | <detail> |

Tested against: <commit hash> (<commit message>)
```

If any check fails, describe what's wrong and suggest a fix.

## Integration

**Called by:** `deploy.dashboard` (as post-deploy verification)
**Pairs with:** `deploy.dashboard`, `sandbox.dashboard`
