# Usage:
#   nix develop # start a nix shell
#   tilt up

if not os.environ.get('ANTHROPIC_API_KEY'):
    fail('ANTHROPIC_API_KEY is not set')

load('ext://uibutton', 'cmd_button', 'location')

cmd_button('reset-data',
    argv=['sh', '-c', 'rm -rf data && echo "data directory deleted" && tilt get uiresource -o name | grep -v Tiltfile | sed "s|.*/||" | xargs -n1 tilt trigger'],
    location=location.NAV,
    icon_name='delete_forever',
    text='Reset data',
)

# ----------------------------------------------------------------------------------------------------------------------
# Setup

local_resource(
    "uv-sync",
    cmd="uv sync",
    deps=["pyproject.toml", "uv.lock"],
    labels=["setup"],
)

# Idempotent
local_resource(
    "cogtainer-create",
    cmd=" ".join([
        "uv run cogtainer create dev --type local",
        "--llm-provider anthropic --llm-api-key-env ANTHROPIC_API_KEY",
        "2>&1 || true",  # ignore "already exists"
    ]),
    resource_deps=["uv-sync"],
    labels=["setup"],
)

# Idempotent
local_resource(
    "cogent-create",
    cmd="uv run cogent create alpha 2>&1 || true",
    resource_deps=["cogtainer-create"],
    labels=["setup"],
)

# ----------------------------------------------------------------------------------------------------------------------
# Cogos

local_resource(
    "cogos",
    serve_cmd="uv run cogos start --foreground 2>&1 | ts '%H:%M:%S'",
    resource_deps=["cogent-create"],
    labels=["cogos"],
)

# ----------------------------------------------------------------------------------------------------------------------
# Dashboard

DASHBOARD_BE_PORT = int(str(local("bash -c 'source dashboard/ports.sh && echo -n $DASHBOARD_BE_PORT'", quiet=True)))
DASHBOARD_FE_PORT = int(str(local("bash -c 'source dashboard/ports.sh && echo -n $DASHBOARD_FE_PORT'", quiet=True)))

local_resource(
    "dashboard-npm-ci",
    cmd="cd dashboard/frontend && npm ci",
    deps=["dashboard/frontend/package.json", "dashboard/frontend/package-lock.json"],
    resource_deps=["uv-sync"],
    labels=["dashboard"],
)

local_resource(
    "dashboard-backend",
    serve_cmd=" ".join([
        "source dashboard/ports.sh &&",
        "USE_LOCAL_DB=1 COGTAINER=dev COGENT=alpha",
        "uv run uvicorn cogos.api.app:app",
        "--host 0.0.0.0 --port $DASHBOARD_BE_PORT 2>&1 | ts '%H:%M:%S'",
    ]),
    resource_deps=["cogent-create", "dashboard-npm-ci"],
    deps=["src/cogos/api", "src/dashboard"],
    links=["http://localhost:%d" % DASHBOARD_BE_PORT],
    labels=["dashboard"],
)

local_resource(
    "dashboard-frontend",
    serve_cmd=" ".join([
        "source dashboard/ports.sh &&",
        "cd dashboard/frontend &&",
        "npx next dev -p $DASHBOARD_FE_PORT 2>&1 | ts '%H:%M:%S'",
    ]),
    resource_deps=["dashboard-npm-ci", "dashboard-backend"],
    deps=["dashboard/frontend/src", "dashboard/frontend/app"],
    links=["http://localhost:%d" % DASHBOARD_FE_PORT],
    labels=["dashboard"],
)
