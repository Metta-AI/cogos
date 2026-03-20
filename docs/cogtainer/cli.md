# Cogtainer CLI Reference

The `cogtainer` CLI manages cogtainer infrastructure — the self-contained environments that host cogents.

## Installation

```bash
uv sync
```

The CLI is registered as `cogtainer` via pyproject.toml.

## Authentication

The cogtainer CLI uses AWS SSO profiles to authenticate. The `--profile` option must resolve to a session with admin access on your AWS management account.

```bash
aws sso login --profile <your-profile>
```

## Global Options

| Option | Default | Description |
|--------|---------|-------------|
| `--profile` | (from `~/.cogos/cogtainers.yml`) | AWS SSO profile for org-level operations |

## Cogtainer Management

### `cogtainer create <name> --type aws`

Create a new cogtainer and deploy all CDK stacks.

```bash
cogtainer create my-cogtainer --type aws
```

This will:
1. Find or create the cogtainer account in the AWS Organization
2. Run CDK deploy to provision all infrastructure

### `cogtainer update <name>`

Update the CDK stacks with any code changes.

```bash
cogtainer update my-cogtainer
```

### `cogtainer destroy <name>`

Tear down all CDK stacks. Prompts for confirmation.

```bash
cogtainer destroy my-cogtainer
```

### `cogtainer status [<name>]`

Show the current state of cogtainer resources (ECR, ECS cluster, DynamoDB).

```bash
cogtainer status
cogtainer status my-cogtainer
```

## Cogent Management

### `cogent create <name>`

Create a new cogent in the current cogtainer (set via `COGTAINER` env var or `~/.cogos/cogtainers.yml`).

```bash
cogent create alpha
```

### `cogent destroy <name>`

Destroy a cogent and its resources.

```bash
cogent destroy alpha
```

### `cogent list`

List all cogents with their current status.

```bash
cogent list
```

Example output:

```
                              Cogents
+---------+-----------------+-------+---------+---------+-------+------------------+
| Name    | Stack Status    | Tasks | Image   | CPU(1m) | Mem % | Channels         |
+---------+-----------------+-------+---------+---------+-------+------------------+
| alpha   | CREATE_COMPLETE | 1/1   | v1.3    | 12      | 45    | discord:ok       |
| beta    | UPDATE_COMPLETE | 1/1   | v2.0    | 8       | 32    | github:ok        |
+---------+-----------------+-------+---------+---------+-------+------------------+
```

## Secrets Management

All secret commands operate on AWS Secrets Manager in the cogtainer account.

### Path Conventions

```
cogent/{cogent_name}/{channel}   # Per-cogent channel credentials
cogtainer/shared/{key_name}      # Org-wide shared keys
```

Examples:
- `cogent/alpha/discord` — Alpha's Discord bot token
- `cogent/alpha/github` — Alpha's GitHub App credentials
- `cogtainer/shared/jwt-signing-key` — Shared JWT signing key

### `cogtainer secrets list`

List all secrets, optionally filtered by cogent name.

```bash
cogtainer secrets list
cogtainer secrets list --cogent alpha
```

| Option | Description |
|--------|-------------|
| `--cogent` | Filter secrets to a specific cogent |

### `cogtainer secrets get <path>`

Retrieve and display a secret value. Access tokens are automatically redacted in output.

```bash
cogtainer secrets get cogent/alpha/discord
```

Output is formatted JSON. The `access_token` field is truncated to the first 8 characters.

### `cogtainer secrets set <path>`

Create or update a secret. Provide the value as inline JSON or from a file.

```bash
# Inline JSON
cogtainer secrets set cogent/alpha/discord --value '{"access_token":"xoxb-...", "type":"oauth"}'

# From file
cogtainer secrets set cogent/alpha/github --file credentials.json
```

| Option | Description |
|--------|-------------|
| `--value` | JSON string with the secret value |
| `--file` | Path to a JSON file containing the secret value |

One of `--value` or `--file` is required.

### `cogtainer secrets delete <path>`

Delete a secret. Prompts for confirmation. Uses force-delete (no recovery window).

```bash
cogtainer secrets delete cogent/alpha/discord
```

### `cogtainer secrets rotate <path>`

Trigger the Secrets Manager rotation Lambda for a secret. The rotation Lambda supports two token types:

- **`github_app`** — Generates RS256 JWT from `app_id` + `private_key`, creates installation access token
- **`oauth`** — Standard `refresh_token` grant flow using `client_id`, `client_secret`, `token_url`

```bash
cogtainer secrets rotate cogent/alpha/github
```
