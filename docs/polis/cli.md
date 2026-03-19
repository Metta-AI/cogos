# Polis CLI Reference

The `polis` CLI manages the shared infrastructure hub for all cogents.

## Installation

```bash
uv pip install -e ".[dev]"
```

The CLI is registered as `polis` via pyproject.toml (`polis.cli:polis`).

## Authentication

Polis uses AWS SSO profiles to authenticate. The `--profile` option must resolve to a session with admin access on your AWS management account. The CLI then assumes `OrganizationAccountAccessRole` into the polis account.

```bash
aws sso login --profile <your-profile>
```

## Global Options

| Option | Default | Description |
|--------|---------|-------------|
| `--profile` | (from `~/.cogos/config.yml`) | AWS SSO profile for org-level operations |

## Stack Management

### `polis create`

Create the polis account (if it doesn't exist) and deploy all CDK stacks.

```bash
polis create
```

This will:
1. Find or create the `cogent-polis` account in the AWS Organization
2. Run `npx cdk deploy --all` to deploy `cogent-polis` and `cogent-secrets` stacks

### `polis update`

Update the CDK stacks with any code changes.

```bash
polis update
```

Runs `npx cdk deploy --all --require-approval never`.

### `polis destroy`

Tear down all CDK stacks. Prompts for confirmation.

```bash
polis destroy
```

Runs `npx cdk destroy --all --force`.

### `polis status`

Show the current state of polis resources (ECR, ECS cluster, DynamoDB).

```bash
polis status
```

Example output:

```
         Polis Resources
┏━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Resource    ┃ Status  ┃ Details                                         ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ECR         │ active  │ <account-id>.dkr.ecr.us-east-1.amazonaws.com/…  │
│ ECS Cluster │ active  │ 2 running tasks                                 │
│ DynamoDB    │ active  │ 3 items                                         │
└─────────────┴─────────┴─────────────────────────────────────────────────┘
```

## Secrets Management

All secret commands operate on AWS Secrets Manager in the polis account.

### Path Conventions

```
cogent/{cogent_name}/{channel}   # Per-cogent channel credentials
polis/shared/{key_name}          # Org-wide shared keys
```

Examples:
- `cogent/alpha/discord` — Alpha's Discord bot token
- `cogent/alpha/github` — Alpha's GitHub App credentials
- `polis/shared/jwt-signing-key` — Shared JWT signing key

### `polis secrets list`

List all secrets, optionally filtered by cogent name.

```bash
polis secrets list
polis secrets list --cogent alpha
```

| Option | Description |
|--------|-------------|
| `--cogent` | Filter secrets to a specific cogent |

### `polis secrets get <path>`

Retrieve and display a secret value. Access tokens are automatically redacted in output.

```bash
polis secrets get cogent/alpha/discord
```

Output is formatted JSON. The `access_token` field is truncated to the first 8 characters.

### `polis secrets set <path>`

Create or update a secret. Provide the value as inline JSON or from a file.

```bash
# Inline JSON
polis secrets set cogent/alpha/discord --value '{"access_token":"xoxb-...", "type":"oauth"}'

# From file
polis secrets set cogent/alpha/github --file credentials.json
```

| Option | Description |
|--------|-------------|
| `--value` | JSON string with the secret value |
| `--file` | Path to a JSON file containing the secret value |

One of `--value` or `--file` is required.

### `polis secrets delete <path>`

Delete a secret. Prompts for confirmation. Uses force-delete (no recovery window).

```bash
polis secrets delete cogent/alpha/discord
```

### `polis secrets rotate <path>`

Trigger the Secrets Manager rotation Lambda for a secret. The rotation Lambda supports two token types:

- **`github_app`** — Generates RS256 JWT from `app_id` + `private_key`, creates installation access token
- **`oauth`** — Standard `refresh_token` grant flow using `client_id`, `client_secret`, `token_url`

```bash
polis secrets rotate cogent/alpha/github
```

## Cogent Status

Status data comes from the watcher Lambda, which polls every 60 seconds and writes to the `cogent-status` DynamoDB table.

### `polis cogents list`

List all cogents with their current status.

```bash
polis cogents list
```

Example output:

```
                              Cogents
┏━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Name  ┃ Stack Status    ┃ Tasks ┃ Image   ┃ CPU(1m) ┃ Mem % ┃ Channels         ┃
┡━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ alpha │ CREATE_COMPLETE │ 1/1   │ v1.3    │ 12      │ 45    │ discord:ok       │
│ beta  │ UPDATE_COMPLETE │ 1/1   │ v2.0    │ 8       │ 32    │ github:ok        │
└───────┴─────────────────┴───────┴─────────┴─────────┴───────┴──────────────────┘
```

### `polis cogents status <name>`

Show detailed JSON status for a single cogent.

```bash
polis cogents status alpha
```

Returns the full DynamoDB record as JSON, including all fields from the watcher Lambda.

## CDK Deployment Details

The CLI wraps `npx cdk` for stack operations. The CDK app is at `src/polis/cdk/app.py` and deploys two stacks:

| Stack | Resources |
|-------|-----------|
| `cogent-polis` | ECS cluster, ECR repo, Route53 zone, DynamoDB table, watcher Lambda |
| `cogent-secrets` | Rotation Lambda, cross-account SecretsReaderRole |

The CDK app is invoked as:

```bash
npx cdk deploy --all --app "python -m polis.cdk.app" -c org_id=<org_id>
```

The `org_id` context variable is passed automatically by the CLI. A hardcoded fallback (`o-n7g18rzou1`) is used if not provided.
