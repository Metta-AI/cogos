# Cogtainer-to-Polis Consolidation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate the standalone cogtainer CDK app. Move shared resources (EventBridge bus, ALB, monitoring) into the polis CDK stack. Move per-cogent CDK code into `src/polis/cdk/stacks/cogent.py`. Wire `polis cogents create` to deploy the per-cogent stack.

**Architecture:** Polis CDK stack gains a shared EventBridge bus, shared ALB with wildcard cert, and shared monitoring. A new `CogentStack` under `src/polis/cdk/stacks/cogent.py` creates per-cogent resources (IAM role, S3 bucket, SQS queue, EventBridge rules, dashboard target group + Fargate service + listener rule). `polis cogents create` deploys this stack after identity setup. Lambdas and ECS task defs are versioned by commit and deployed by CI — the cogent stack only references them.

**Tech Stack:** AWS CDK (Python), boto3, Click CLI

---

### Task 1: Add shared EventBridge bus to polis CDK stack

**Files:**
- Modify: `src/polis/cdk/stacks/core.py`
- Modify: `src/polis/naming.py`

**Step 1: Add naming helper for shared bus**

In `src/polis/naming.py`, add:

```python
def shared_event_bus_name() -> str:
    return f"{RESOURCE_PREFIX}-polis-events"
```

**Step 2: Add EventBridge bus to PolisStack**

In `src/polis/cdk/stacks/core.py`, after the DynamoDB status table section, add:

```python
# --- Shared EventBridge Bus ---
self.event_bus = events.EventBus(
    self,
    "SharedEventBus",
    event_bus_name=naming.shared_event_bus_name(),
)
```

Add a CfnOutput:

```python
cdk.CfnOutput(self, "SharedEventBusArn", value=self.event_bus.event_bus_arn)
cdk.CfnOutput(self, "SharedEventBusName", value=self.event_bus.event_bus_name)
```

**Step 3: Commit**

```bash
git add src/polis/cdk/stacks/core.py src/polis/naming.py
git commit -m "feat(polis): add shared EventBridge bus to polis CDK stack"
```

---

### Task 2: Add shared ALB to polis CDK stack

**Files:**
- Modify: `src/polis/cdk/stacks/core.py`

**Step 1: Add shared ALB with wildcard cert**

In `src/polis/cdk/stacks/core.py`, add after the shared EventBridge bus section:

```python
# --- Shared ALB for cogent dashboards ---
vpc = ec2.Vpc.from_lookup(self, "SharedVpc", is_default=True)
public_subnets = ec2.SubnetSelection(
    subnet_type=ec2.SubnetType.PUBLIC,
    one_per_az=True,
)

self.shared_alb = elbv2.ApplicationLoadBalancer(
    self,
    "SharedALB",
    vpc=vpc,
    internet_facing=True,
    vpc_subnets=public_subnets,
)

# Wildcard cert for *.softmax-cogents.com
wildcard_cert_arn = self.node.try_get_context("wildcard_cert_arn") or ""
if wildcard_cert_arn:
    self.https_listener = self.shared_alb.add_listener(
        "HttpsListener",
        port=443,
        certificates=[elbv2.ListenerCertificate.from_arn(wildcard_cert_arn)],
        default_action=elbv2.ListenerAction.fixed_response(
            status_code=404,
            content_type="text/plain",
            message_body="Not found",
        ),
    )

    self.shared_alb.add_redirect(
        source_port=80,
        target_port=443,
        target_protocol=elbv2.ApplicationProtocol.HTTPS,
    )
else:
    self.https_listener = None
```

Note: You'll need to import `aws_elasticloadbalancingv2 as elbv2` at the top — check if it's already imported.

Add CfnOutputs:

```python
cdk.CfnOutput(self, "SharedAlbArn", value=self.shared_alb.load_balancer_arn)
cdk.CfnOutput(self, "SharedAlbDns", value=self.shared_alb.load_balancer_dns_name)
if self.https_listener:
    cdk.CfnOutput(self, "SharedHttpsListenerArn", value=self.https_listener.listener_arn)
```

**Step 2: Add wildcard cert context to polis CDK app**

In `src/polis/cdk/app.py`, pass the wildcard_cert_arn context through to the stack.

**Step 3: Commit**

```bash
git add src/polis/cdk/stacks/core.py src/polis/cdk/app.py
git commit -m "feat(polis): add shared ALB with wildcard cert for cogent dashboards"
```

---

### Task 3: Create CogentStack in polis CDK

This is the per-cogent stack that replaces CogtainerStack. It creates: IAM role, S3 bucket, SQS queue, EventBridge rules on the shared bus, and dashboard (target group + Fargate + listener rule on shared ALB).

**Files:**
- Create: `src/polis/cdk/stacks/cogent.py`

**Step 1: Create the CogentStack**

Create `src/polis/cdk/stacks/cogent.py` with the per-cogent stack. Key differences from the old CogtainerStack:

1. **No Lambdas or ECS task defs** — these are shared, versioned by CI
2. **No EventBridge bus** — uses shared polis bus, creates per-cogent rules
3. **No per-cogent ALB** — creates target group + Fargate service + listener rule on shared ALB
4. **Per-cogent IAM role** — assumed by shared Lambdas/ECS at runtime

```python
"""Per-cogent CDK stack — lightweight wiring deployed by polis CLI."""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from polis import naming

_PROJECT_ROOT = str(Path(__file__).resolve().parents[4])


class CogentStack(Stack):
    """Per-cogent infrastructure: IAM, storage, queues, event rules, dashboard."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        cogent_name: str,
        domain: str,
        shared_event_bus_name: str,
        shared_db_cluster_arn: str,
        shared_db_secret_arn: str,
        shared_alb_listener_arn: str,
        shared_alb_security_group_id: str,
        certificate_arn: str = "",
        ecr_repo_uri: str = "",
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)

        safe_name = cogent_name.replace(".", "-")
        db_name = f"cogent_{safe_name.replace('-', '_')}"
        cdk.Tags.of(self).add("cogent_name", cogent_name)

        # --- Per-cogent IAM Role (assumed by shared Lambdas/ECS) ---
        self.cogent_role = iam.Role(
            self,
            "CogentRole",
            role_name=naming.iam_role_name(f"{safe_name}-runtime"),
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal("lambda.amazonaws.com"),
                iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            ),
        )

        # Data API access to this cogent's database
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement"],
                resources=[shared_db_cluster_arn],
            )
        )
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    shared_db_secret_arn,
                    f"arn:aws:secretsmanager:*:*:secret:cogent/{cogent_name}/*",
                    "arn:aws:secretsmanager:*:*:secret:cogent/polis/*",
                ],
            )
        )
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["events:PutEvents"],
                resources=["*"],
            )
        )
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:Converse", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"],
            )
        )
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ses:SendEmail", "ses:SendRawEmail"],
                resources=[f"arn:aws:ses:*:*:identity/{domain}", "arn:aws:ses:*:*:identity/*"],
            )
        )
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[f"arn:aws:lambda:*:*:function:{naming.lambda_name(safe_name, '*')}"],
            )
        )
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask", "iam:PassRole"],
                resources=["*"],
            )
        )
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ssmmessages:CreateControlChannel",
                    "ssmmessages:CreateDataChannel",
                    "ssmmessages:OpenControlChannel",
                    "ssmmessages:OpenDataChannel",
                ],
                resources=["*"],
            )
        )
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[f"arn:aws:iam::*:role/{naming.iam_role_name(f'{safe_name}-tool')}-*"],
            )
        )

        # --- S3 Sessions Bucket ---
        self.sessions_bucket = s3.Bucket(
            self,
            "SessionsBucket",
            bucket_name=naming.bucket_name(cogent_name),
            removal_policy=cdk.RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-old-sessions",
                    prefix="sessions/",
                    expiration=Duration.days(30),
                ),
            ],
        )
        self.sessions_bucket.grant_read_write(self.cogent_role)

        # --- SQS FIFO Ingress Queue ---
        self.ingress_queue = sqs.Queue(
            self,
            "IngressQueue",
            queue_name=f"{naming.queue_name(safe_name, 'cogos-ingress')}.fifo",
            fifo=True,
            content_based_deduplication=False,
            visibility_timeout=Duration.seconds(60),
        )
        self.ingress_queue.grant_send_messages(self.cogent_role)

        # --- EventBridge Rules (on shared polis bus) ---
        shared_bus = events.EventBus.from_event_bus_name(
            self, "SharedBus", shared_event_bus_name,
        )

        events.Rule(
            self,
            "CatchAllRule",
            event_bus=shared_bus,
            rule_name=naming.rule_name(safe_name, "catch-all"),
            event_pattern=events.EventPattern(
                source=events.Match.prefix("cogent."),
                detail={"cogent_name": [cogent_name]},
            ),
            targets=[targets.LambdaFunction(
                handler=lambda_.Function.from_function_name(
                    self, "OrchestratorRef",
                    naming.lambda_name(safe_name, "orchestrator"),
                ),
            )],
        )

        events.Rule(
            self,
            "DispatcherSchedule",
            rule_name=naming.rule_name(safe_name, "dispatcher-schedule"),
            schedule=events.Schedule.rate(Duration.minutes(1)),
            targets=[targets.LambdaFunction(
                handler=lambda_.Function.from_function_name(
                    self, "DispatcherRef",
                    naming.lambda_name(safe_name, "dispatcher"),
                ),
            )],
        )

        # --- Shared Discord Reply Queue access ---
        polis_discord_queue = sqs.Queue.from_queue_arn(
            self, "PolisDiscordQueue",
            f"arn:aws:sqs:{self.region}:{self.account}:{naming.queue_name('polis', 'discord-replies')}",
        )
        polis_discord_queue.grant_send_messages(self.cogent_role)

        # --- Dashboard (target group + Fargate on shared ALB) ---
        if certificate_arn and shared_alb_listener_arn:
            self._create_dashboard(
                cogent_name=cogent_name,
                safe_name=safe_name,
                domain=domain,
                db_name=db_name,
                shared_db_cluster_arn=shared_db_cluster_arn,
                shared_db_secret_arn=shared_db_secret_arn,
                shared_alb_listener_arn=shared_alb_listener_arn,
                shared_alb_security_group_id=shared_alb_security_group_id,
                ecr_repo_uri=ecr_repo_uri,
            )

        # --- Outputs ---
        CfnOutput(self, "CogentName", value=cogent_name)
        CfnOutput(self, "CogentRoleArn", value=self.cogent_role.role_arn)
        CfnOutput(self, "SessionsBucket", value=self.sessions_bucket.bucket_name)
        CfnOutput(self, "IngressQueueUrl", value=self.ingress_queue.queue_url)

    def _create_dashboard(
        self,
        *,
        cogent_name: str,
        safe_name: str,
        domain: str,
        db_name: str,
        shared_db_cluster_arn: str,
        shared_db_secret_arn: str,
        shared_alb_listener_arn: str,
        shared_alb_security_group_id: str,
        ecr_repo_uri: str,
    ) -> None:
        """Create dashboard target group + Fargate service + ALB listener rule."""
        vpc = ec2.Vpc.from_lookup(self, "DashVpc", is_default=True)
        cluster = ecs.Cluster.from_cluster_attributes(
            self, "PolisCluster",
            cluster_name=naming.cluster_name(),
            vpc=vpc,
            security_groups=[],
        )
        public_subnets = ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PUBLIC,
            one_per_az=True,
        )

        # Target group
        target_group = elbv2.ApplicationTargetGroup(
            self, "DashTG",
            vpc=vpc,
            port=5174,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/healthz",
                healthy_http_codes="200",
                interval=Duration.seconds(30),
            ),
        )

        # Listener rule on shared ALB (host-based routing)
        listener = elbv2.ApplicationListener.from_application_listener_attributes(
            self, "SharedListener",
            listener_arn=shared_alb_listener_arn,
            security_group=ec2.SecurityGroup.from_security_group_id(
                self, "SharedAlbSg", shared_alb_security_group_id,
            ),
        )

        elbv2.ApplicationListenerRule(
            self, "DashHostRule",
            listener=listener,
            priority=self._listener_priority(safe_name),
            conditions=[
                elbv2.ListenerCondition.host_headers([f"{safe_name}.{domain}"]),
            ],
            target_groups=[target_group],
        )

        # Task definition
        task_def = ecs.FargateTaskDefinition(self, "DashTaskDef", cpu=256, memory_limit_mib=512)

        docker_version = (
            (Path(_PROJECT_ROOT) / "dashboard" / "DOCKER_VERSION").read_text().strip()
        )

        db_env = {
            "COGENT_NAME": cogent_name,
            "DASHBOARD_COGENT_NAME": cogent_name,
            "DB_RESOURCE_ARN": shared_db_cluster_arn,
            "DB_CLUSTER_ARN": shared_db_cluster_arn,
            "DB_SECRET_ARN": shared_db_secret_arn,
            "DB_NAME": db_name,
            "EVENT_BUS_NAME": naming.shared_event_bus_name(),
            "SESSIONS_BUCKET": self.sessions_bucket.bucket_name,
            "DASHBOARD_ASSETS_S3": f"s3://{self.sessions_bucket.bucket_name}/dashboard/frontend.tar.gz",
            "DASHBOARD_DOCKER_VERSION": docker_version,
            "EXECUTOR_FUNCTION_NAME": naming.lambda_name(safe_name, "executor"),
        }

        task_def.add_container(
            "web",
            image=ecs.ContainerImage.from_asset(
                _PROJECT_ROOT,
                file="dashboard/Dockerfile",
                platform=aws_cdk.aws_ecr_assets.Platform.LINUX_AMD64,
            ),
            port_mappings=[ecs.PortMapping(container_port=5174)],
            environment=db_env,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="dashboard"),
        )

        # Grant dashboard task role the same permissions as cogent role
        for stmt in self.cogent_role.assume_role_policy.statements:
            pass  # Role is separate — grant directly
        task_def.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement"],
                resources=[shared_db_cluster_arn],
            )
        )
        task_def.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    shared_db_secret_arn,
                    f"arn:aws:secretsmanager:*:*:secret:cogent/{cogent_name}/*",
                ],
            )
        )
        task_def.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:DescribeServices", "events:PutEvents", "logs:FilterLogEvents", "lambda:InvokeFunction"],
                resources=["*"],
            )
        )
        self.sessions_bucket.grant_read_write(task_def.task_role)

        # Security group
        sg = ec2.SecurityGroup(self, "DashSg", vpc=vpc)
        sg.add_ingress_rule(
            ec2.Peer.security_group_id(shared_alb_security_group_id),
            ec2.Port.tcp(5174),
        )

        # Fargate service
        service = ecs.FargateService(
            self, "DashService",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            assign_public_ip=True,
            security_groups=[sg],
            vpc_subnets=public_subnets,
        )
        target_group.add_target(service)

        self.dashboard_service = service
        self.dashboard_url = f"https://{safe_name}.{domain}"
        CfnOutput(self, "DashboardUrl", value=self.dashboard_url)

    @staticmethod
    def _listener_priority(safe_name: str) -> int:
        """Deterministic priority from cogent name (1-50000 range)."""
        return (hash(safe_name) % 49999) + 1
```

Note: The Lambda references in the EventBridge rules use `from_function_name` to reference existing shared Lambdas. You'll need to add `from aws_cdk import aws_lambda as lambda_` to the imports.

**Step 2: Commit**

```bash
git add src/polis/cdk/stacks/cogent.py
git commit -m "feat(polis): add CogentStack for per-cogent infrastructure"
```

---

### Task 4: Add CogentStack CDK app entry point

**Files:**
- Modify: `src/polis/cdk/app.py`

**Step 1: Add cogent stack deployment mode**

The polis CDK app needs to support deploying both the polis stack and individual cogent stacks. Add a `cogent_name` context variable that, when set, deploys a CogentStack instead of (or in addition to) the PolisStack.

Look at how the existing cogtainer `app.py` works (`src/cogtainer/cdk/app.py`) and replicate the pattern — read context variables like `cogent_name`, `certificate_arn`, `shared_db_cluster_arn`, etc. and create a `CogentStack`.

**Step 2: Commit**

```bash
git add src/polis/cdk/app.py
git commit -m "feat(polis): add cogent stack deployment to polis CDK app"
```

---

### Task 5: Wire `polis cogents create` to deploy CogentStack

**Files:**
- Modify: `src/polis/cli.py`

**Step 1: Add cogent CDK deploy after identity setup**

In `cogents_create()`, after step 7 (identity secret), add:

```python
# 8. Deploy per-cogent CDK stack
console.print("  Deploying cogent infrastructure stack...")
_deploy_cogent_stack(name, cert_arn, cluster_arn, secret_arn, ecr_repo_uri, profile)
```

Add the helper function:

```python
def _deploy_cogent_stack(
    name: str,
    certificate_arn: str,
    db_cluster_arn: str,
    db_secret_arn: str,
    ecr_repo_uri: str,
    profile: str | None,
) -> None:
    """Deploy the per-cogent CDK stack via polis CDK app."""
    safe_name = name.replace(".", "-")
    cmd = [
        "npx", "cdk", "deploy", naming.stack_name(name),
        "-c", f"cogent_name={name}",
        "-c", f"certificate_arn={certificate_arn}",
        "-c", f"shared_db_cluster_arn={db_cluster_arn}",
        "-c", f"shared_db_secret_arn={db_secret_arn}",
        "-c", f"ecr_repo_uri={ecr_repo_uri}",
        "--app", "python -m polis.cdk.app",
        "--require-approval", "never",
    ]
    env = {**os.environ, "AWS_PROFILE": resolve_org_profile(profile)}
    result = subprocess.run(cmd, capture_output=False, env=env)
    if result.returncode != 0:
        raise click.ClickException("Cogent CDK deploy failed")
```

**Step 2: Wire `polis cogents destroy` to tear down the CDK stack**

In `cogents_destroy()`, before the existing cleanup steps, add:

```python
# 0. Destroy per-cogent CDK stack
console.print("  Destroying cogent infrastructure stack...")
try:
    _destroy_cogent_stack(name, profile)
except Exception as e:
    console.print(f"  [yellow]Stack destroy: {e}[/yellow]")
```

**Step 3: Commit**

```bash
git add src/polis/cli.py
git commit -m "feat(polis): wire cogents create/destroy to deploy CogentStack"
```

---

### Task 6: Update cogtainer CLI to use polis-deployed stack

**Files:**
- Modify: `src/cogtainer/cli.py`
- Modify: `src/cogtainer/update_cli.py`

**Step 1: Remove `cogtainer create` and `cogtainer destroy` CDK commands**

In `src/cogtainer/cli.py`:
- Remove `create_cmd` (lines 186-378) — now handled by `polis cogents create`
- Remove `destroy_cmd` (lines 391-417) — now handled by `polis cogents destroy`
- Remove `build_cmd` (lines 536-588) — executor images deployed by CI
- Keep `status_cmd`, `cleanup_cmd`, `await_cmd`, and the `update` subgroup

**Step 2: Update `update stack` command**

In `src/cogtainer/update_cli.py`, update the `update_stack` command to use `polis.cdk.app` instead of `cogtainer.cdk.app`:

Change `--app "python -m cogtainer.cdk.app"` to `--app "python -m polis.cdk.app"`.

**Step 3: Update status command**

The status command references the cogtainer stack outputs. Update it to read from the polis-deployed cogent stack (same stack name pattern, just deployed differently).

**Step 4: Remove references to `cogtainer.cdk`**

Remove imports of `cogtainer.cdk.config`, `cogtainer.cdk.stack`, etc. from CLI files.

**Step 5: Commit**

```bash
git add src/cogtainer/cli.py src/cogtainer/update_cli.py
git commit -m "refactor(cogtainer): remove CDK commands, use polis-deployed stack"
```

---

### Task 7: Remove old cogtainer CDK code

**Files:**
- Delete: `src/cogtainer/cdk/app.py`
- Delete: `src/cogtainer/cdk/stack.py`
- Delete: `src/cogtainer/cdk/config.py`
- Delete: `src/cogtainer/cdk/constructs/compute.py`
- Delete: `src/cogtainer/cdk/constructs/monitoring.py`
- Delete: `src/cogtainer/cdk/constructs/eventbridge.py`
- Delete: `src/cogtainer/cdk/constructs/__init__.py`
- Delete: `src/cogtainer/cdk/__init__.py` (if exists)

**Step 1: Verify no remaining imports**

```bash
grep -r "from cogtainer.cdk" src/ --include="*.py"
grep -r "cogtainer.cdk.app" src/ --include="*.py"
```

Fix any remaining references.

**Step 2: Delete the files**

```bash
rm -rf src/cogtainer/cdk/
```

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove old cogtainer CDK code (now in polis)"
```

---

### Task 8: Update shared monitoring in polis

**Files:**
- Modify: `src/polis/cdk/stacks/core.py`

**Step 1: Add shared CloudWatch monitoring**

Add alarms that use cogent-name dimensions from Lambda metrics. These replace the per-cogent MonitoringConstruct. The metrics are available because Lambda function names follow the pattern `cogent-{safe_name}-{type}`.

This is lower priority and can use metric math with wildcards or be added iteratively as cogents are created.

**Step 2: Commit**

```bash
git add src/polis/cdk/stacks/core.py
git commit -m "feat(polis): add shared CloudWatch monitoring for all cogents"
```

---

### Task 9: Remove S3 bucket creation from polis CLI

**Files:**
- Modify: `src/polis/cli.py`

**Step 1: Remove imperative S3 bucket creation from `cogents_create`**

The S3 bucket is now created by the CogentStack CDK. Remove the boto3 S3 bucket creation code (step 6 in current `cogents_create`).

**Step 2: Commit**

```bash
git add src/polis/cli.py
git commit -m "refactor(polis): remove imperative S3 creation, now in CogentStack CDK"
```

---

### Task 10: Integration test — verify CDK synth

**Step 1: Test polis CDK synth**

```bash
cd /Users/daveey/code/cogents/cogents.3
npx cdk synth --app "python -m polis.cdk.app" -c org_id=test 2>&1 | head -50
```

Verify no errors and the shared EventBridge bus + ALB appear in the template.

**Step 2: Test cogent CDK synth**

```bash
npx cdk synth --app "python -m polis.cdk.app" -c cogent_name=test -c shared_db_cluster_arn=arn:aws:rds:us-east-1:123:cluster:test -c shared_db_secret_arn=arn:aws:secretsmanager:us-east-1:123:secret:test 2>&1 | head -50
```

Verify the CogentStack synthesizes correctly.

**Step 3: Commit any fixes**

---

## Execution Order

Tasks 1-2 can be done in parallel (both modify core.py but different sections).
Task 3 depends on Tasks 1-2 (references shared bus and ALB).
Task 4 depends on Task 3.
Task 5 depends on Task 4.
Tasks 6-7 depend on Task 5.
Task 8 is independent (can be done in parallel with 6-7).
Task 9 depends on Task 3 (S3 now in CDK).
Task 10 depends on all others.

## Parallelizable groups:
- **Group A**: Tasks 1 + 2 (polis shared resources)
- **Group B**: Task 3 (CogentStack — depends on A)
- **Group C**: Task 4 + 5 (app entry point + CLI wiring — sequential, depends on B)
- **Group D**: Tasks 6 + 7 + 9 (cleanup — depends on C)
- **Group E**: Task 8 (monitoring — independent after A)
- **Group F**: Task 10 (integration test — depends on all)
