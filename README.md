# cogos

CogOS -- an autonomous software engineering agent built on the Viable System Model.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- AWS credentials with [Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/setting-up.html) access (for LLM calls)

CogOS uses Claude on AWS Bedrock. You need an AWS account with Bedrock model access enabled for `us.anthropic.claude-sonnet-4-5-*` in your region (default: `us-east-1`). Configure credentials via `aws configure` or AWS SSO.

## Getting Started

```bash
# 1. Install
uv sync --all-extras

# 2. Boot the default image
uv run cogos local cogos image boot cogos --clean

# 3. Start the interactive shell
uv run cogos local shell
```

Inside the shell, start a conversation:

```
cogos:/$ llm -i
llm> hello, what can you do?
```

That's it. The shell calls Bedrock directly — no executor loop, no extra services.

### What just happened

- `cogos local` uses a JSON-backed local store (`.local/cogos/cogos_data.json`) instead of AWS RDS/Lambda. No cloud infrastructure needed beyond Bedrock.
- `image boot cogos --clean` loaded the default cogent image from `images/cogos/` — capabilities, processes, handlers, and files.
- `shell` opened an interactive session. `llm -i` starts a multi-turn conversation with your cogent via Bedrock.

Other shell commands: `help`, `llm -v <prompt>` (verbose with tool traces), `files ls`, `caps ls`, `procs ls`.

## Running the Executor Loop

The shell is good for interactive use. For event-driven execution (channel messages triggering processes), run the local executor:

```bash
# Terminal 1: start the executor (polls every 2s, replaces Lambda dispatch)
uv run cogos local cogos run-local

# Terminal 2: send a message to trigger a process
uv run cogos local cogos channel send io:discord:dm \
  --payload '{"content":"hello","author":"tester","author_id":"1","channel_id":"2","message_type":"discord:dm","is_dm":true,"is_mention":false,"attachments":[],"embeds":[]}'

# Or run a single tick
uv run cogos local cogos run-local --once

# Inspect runs
uv run cogos local cogos run list --limit 5
```

## Dashboard

The dashboard gives you a web UI for processes, files, capabilities, handlers, runs, and events.

```bash
# Install frontend dependencies (one-time)
cd dashboard/frontend && npm ci && cd ../..

# Start both backend and frontend
uv run cogos local cogos dashboard start
```

The URL will be printed (usually `http://localhost:29489`).

```bash
uv run cogos local cogos dashboard reload   # stop + start
uv run cogos local cogos dashboard stop     # stop both
```

Logs: `/tmp/cogos-backend.log`, `/tmp/cogos-frontend.log`

To run backend and frontend separately:

```bash
# Terminal 1
USE_LOCAL_DB=1 uv run uvicorn dashboard.app:app --host 0.0.0.0 --port 8100

# Terminal 2
cd dashboard/frontend && npm run dev
```

## Deploying to AWS

Local mode is good for development. To deploy a cogent with persistent infrastructure (RDS, Lambda, ECS, Discord bridge), see the [deployment guide](docs/deploy.md).

The short version:

```bash
polis create                              # shared infrastructure (one-time)
cogos <name> cogtainer create             # per-cogent infrastructure
cogos <name> cogos image boot cogos       # load application image
cogos <name> cogos io discord start       # start Discord bridge
```

This requires AWS Organizations, a domain for DNS, and secrets configured in AWS Secrets Manager. See [AGENTS.md](AGENTS.md) for the full operational reference.

## Troubleshooting

**LLM calls fail:** Ensure AWS credentials are configured and Bedrock model access is enabled for Claude Sonnet 4.5 in `us-east-1`. Check with `aws bedrock list-foundation-models --region us-east-1 | grep claude`.

**`image boot` shows no capabilities:** Make sure you used `--clean` to wipe stale state.

**Executor runs but nothing happens:** Check that handlers exist with `uv run cogos local cogos handler list`. If empty, re-run `image boot cogos --clean`.

**Dashboard frontend fails to start:** Run `cd dashboard/frontend && npm ci` first.

## References

- [AGENTS.md](AGENTS.md) — repo operating notes, deployment reference, infrastructure details
- [docs/deploy.md](docs/deploy.md) — deployment guide
- [docs/cogos/guide.md](docs/cogos/guide.md) — CogOS concepts and architecture
- [docs/polis/](docs/polis/) — shared infrastructure (polis) design and CLI reference
- [tests/cogos/local_validation.md](tests/cogos/local_validation.md) — step-by-step local validation checklist
