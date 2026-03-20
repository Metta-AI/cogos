# Cogtainer Infrastructure Consolidation into Polis

## Goal

Eliminate the standalone cogtainer CDK app. All infrastructure is owned by polis — shared resources in the polis CDK stack, per-cogent resources in a cogent CDK stack deployed by `polis cogents create`.

## Architecture

```
Polis CDK Stack (deployed once, shared)
├── Aurora Serverless v2 cluster (done)
├── ECS cluster + ECR (done)
├── EventBridge bus (NEW — replaces per-cogent buses)
├── ALB with wildcard cert *.softmax-cogents.com (NEW)
├── Lambda functions (versioned by commit, deployed by CI)
├── ECS task definitions (versioned by commit, deployed by CI)
├── Monitoring (alarms + dashboards, cogent-name dimensions) (NEW)
├── DynamoDB status table (done)
├── Discord bridge Fargate service (done)
├── Route53 hosted zone (done)
├── S3 ci-artifacts (done)
└── IAM: polis-admin, github-actions (done)

Cogent CDK Stack (per cogent, deployed by polis CLI)
├── IAM role (per-cogent, assumed by shared Lambdas/ECS at runtime)
├── S3 sessions bucket
├── SQS FIFO ingress queue
├── EventBridge rules (on shared polis bus, filtered by cogent name)
└── Dashboard: target group + Fargate service + ALB listener rule
```

## Key Decisions

1. **Shared EventBridge bus** — one bus in polis, per-cogent rules in the cogent stack filter by cogent name. Eliminates N buses.

2. **Shared ALB, per-cogent routing** — polis owns one ALB with HTTPS on `*.softmax-cogents.com`. Each cogent stack creates a target group, Fargate service, and host-based listener rule (`cogent-name.softmax-cogents.com`).

3. **Shared Lambdas + ECS task defs** — versioned by commit, deployed by CI to polis. Cogent stack does not create these, only references them.

4. **Per-cogent IAM role assumption** — shared Lambdas/ECS tasks assume a per-cogent IAM role at runtime. Role grants access to that cogent's specific resources (bucket, queue, DB). Tight isolation.

5. **Shared monitoring** — alarms and dashboards in polis, scoped by cogent-name dimension. No per-cogent CloudWatch resources.

6. **Cogtainer CDK code moves to polis** — `src/cogtainer/cdk/` moves to `src/polis/cdk/stacks/cogent.py` (and constructs as needed). Cogtainer module retains CLI, lambdas, and runtime code only.

## Provisioning Flow

`polis cogents create <name>`:
1. Register domain in Cloudflare DNS
2. Request ACM certificate
3. Register cogent in DynamoDB status table
4. Create database on shared Aurora cluster
5. Deploy cogent CDK stack (creates IAM role, S3 bucket, SQS queue, EventBridge rules, dashboard)

`polis cogents destroy <name>`:
1. Destroy cogent CDK stack
2. Delete database
3. Remove DynamoDB entry
4. Clean up DNS/cert

## What Gets Deleted

- `src/cogtainer/cdk/` — entire CDK app (app.py, stack.py, constructs/)
- `src/cogtainer/cdk/config.py` — stack config (replaced by polis context)
- Per-cogent EventBridge buses
- Per-cogent Lambda deployments (now shared via CI)
- Per-cogent ECS task definitions (now shared via CI)
- Per-cogent CloudWatch alarms/log groups (now shared monitoring)
- `cogtainer deploy` / `cogtainer update` stack commands

## What Stays in Cogtainer Module

- `src/cogtainer/lambdas/` — Lambda handler code (deployed to polis by CI)
- `src/cogtainer/db/` — database models and migrations
- `src/cogtainer/cli.py` — runtime operations (cleanup, etc.)
- Runtime code consumed by Lambdas/ECS tasks
