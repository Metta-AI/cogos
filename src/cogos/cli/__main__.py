"""CogOS CLI — management interface for processes, files, capabilities, and channels."""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path
from uuid import UUID

import click


def _resolve_image_dir(name: str) -> Path | None:
    """Find an image directory by name, checking multiple locations."""
    # 1. CWD images/ (user project)
    cwd_images = Path.cwd() / "images" / name
    if cwd_images.is_dir():
        return cwd_images

    # 2. Repo root images/ (dev checkout)
    repo_images = Path(__file__).resolve().parents[3] / "images" / name
    if repo_images.is_dir():
        return repo_images

    # 3. Bundled package images (pip install)
    bundled = Path(__file__).resolve().parents[1] / "_bundled_images" / name
    if bundled.is_dir():
        return bundled

    return None

from cli.local_dev import apply_local_checkout_env, repo_root, resolve_dashboard_ports

_bedrock_session = None


def _ensure_db_env(cogent_name: str) -> None:
    """Set DB env vars from the shared polis Aurora cluster."""
    if os.environ.get("USE_LOCAL_DB") == "1":
        return

    global _bedrock_session
    import boto3
    orig = boto3.Session()
    creds = orig.get_credentials()
    if creds:
        frozen = creds.get_frozen_credentials()
        _bedrock_session = boto3.Session(
            aws_access_key_id=frozen.access_key,
            aws_secret_access_key=frozen.secret_key,
            aws_session_token=frozen.token,
        )

    from polis.aws import get_polis_session, set_org_profile

    safe_name = cogent_name.replace(".", "-")
    db_name = f"cogent_{safe_name.replace('-', '_')}"

    try:
        set_org_profile()
        session, _ = get_polis_session()
    except Exception:
        return

    # Look up DB connection info from DynamoDB cogent-status table
    ddb = session.resource("dynamodb", region_name="us-east-1")
    try:
        item = ddb.Table("cogent-status").get_item(Key={"cogent_name": cogent_name}).get("Item", {})
        db_info = item.get("database", {})
    except Exception:
        db_info = {}

    if db_info.get("cluster_arn"):
        os.environ.setdefault("DB_RESOURCE_ARN", db_info["cluster_arn"])
        os.environ.setdefault("DB_CLUSTER_ARN", db_info["cluster_arn"])
    if db_info.get("secret_arn"):
        os.environ.setdefault("DB_SECRET_ARN", db_info["secret_arn"])
    os.environ.setdefault("DB_NAME", db_info.get("db_name", db_name))

    creds = session.get_credentials().get_frozen_credentials()
    os.environ["AWS_ACCESS_KEY_ID"] = creds.access_key
    os.environ["AWS_SECRET_ACCESS_KEY"] = creds.secret_key
    if creds.token:
        os.environ["AWS_SESSION_TOKEN"] = creds.token
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")


def _repo():
    ctx = click.get_current_context()
    runtime = ctx.obj.get("runtime")
    if runtime:
        return runtime.get_repository(ctx.obj["cogent_name"])
    from cogos.db.factory import create_repository

    return create_repository()


def _bedrock_client():
    """Get a Bedrock client using original (non-polis) AWS credentials."""
    if _bedrock_session:
        return _bedrock_session.client("bedrock-runtime", region_name="us-east-1")
    import boto3
    return boto3.client("bedrock-runtime", region_name="us-east-1")


def _output(data, *, use_json: bool = False) -> None:
    if use_json:
        click.echo(json.dumps(data, indent=2, default=str))
        return
    if isinstance(data, list):
        for item in data:
            _output_single(item)
            click.echo()
    else:
        _output_single(data)


def _output_single(data: dict) -> None:
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            click.echo(f"  {key}: {json.dumps(value, default=str)}")
        else:
            click.echo(f"  {key}: {value}")


def _default_cogent() -> str:
    from polis.config import deploy_config
    return deploy_config("default_cogent", "")


@click.group()
@click.pass_context
def cogos(ctx: click.Context):
    """CogOS — management CLI for processes, files, capabilities, and channels.

    \b
    Set COGTAINER/COGENT env vars (with cogtainers.yml) or
    COGENT_ID / default_cogent in ~/.cogos/config.yml to target a cogent.
    """
    ctx.ensure_object(dict)

    # --- Try new cogtainer config first ---
    try:
        from cogtainer.cogtainer_cli import _config_path
        from cogtainer.config import load_config

        cfg = load_config(_config_path())

        if cfg.cogtainers:
            from cogtainer.config import resolve_cogent_name, resolve_cogtainer_name
            from cogtainer.runtime.factory import create_runtime

            cogtainer_name = resolve_cogtainer_name(cfg)
            entry = cfg.cogtainers[cogtainer_name]
            runtime = create_runtime(entry, cogtainer_name=cogtainer_name)
            ctx.obj["runtime"] = runtime
            ctx.obj["cogtainer_name"] = cogtainer_name

            cogents = runtime.list_cogents()
            if cogents:
                cogent_name = resolve_cogent_name(cogents)
                ctx.obj["cogent_name"] = cogent_name

            if entry.type in ("local", "docker"):
                os.environ["USE_LOCAL_DB"] = "1"
            else:
                if ctx.obj.get("cogent_name"):
                    _ensure_db_env(ctx.obj["cogent_name"])
            return
    except ValueError:
        # resolve functions raise ValueError when they can't determine a name;
        # allow --help to still work
        if "--help" in sys.argv or "-h" in sys.argv:
            return
        raise
    except Exception:
        # cogtainer modules not available or config load failed — fall through
        pass

    # --- Legacy path: COGENT_ID / default_cogent ---
    cogent = os.environ.get("COGENT_ID") or _default_cogent()
    if not cogent:
        # Allow --help on subcommands without requiring a cogent
        if ctx.invoked_subcommand is None or "--help" in sys.argv or "-h" in sys.argv:
            return
        raise click.UsageError("No cogent specified. Set COGENT_ID env var or default_cogent in ~/.cogos/config.yml")
    ctx.obj["cogent_name"] = cogent
    if cogent == "local":
        apply_local_checkout_env()
    else:
        _ensure_db_env(cogent)


# ═══════════════════════════════════════════════════════════
# IMAGE commands
# ═══════════════════════════════════════════════════════════

@cogos.group()
def image():
    """Manage CogOS images (boot, snapshot, list)."""


def _run_migrations(repo) -> None:
    """Run cogtainer schema migrations (via Data API) and CogOS SQL file migrations."""
    # 1. Cogtainer-level versioned migrations (events, memory, programs, etc.)
    if os.environ.get("USE_LOCAL_DB") != "1":
        try:
            from cogos.db.migrations import apply_schema
            version = apply_schema()
            click.echo(f"Cogtainer schema at version {version}.")
        except Exception as e:
            click.echo(f"Warning: cogtainer migrations failed: {e}")

    # 2. CogOS SQL file migrations (cogos_* tables)
    from cogos.db.migrations import apply_cogos_sql_migrations

    apply_cogos_sql_migrations(
        repo,
        on_error=lambda migration_name, exc: click.echo(f"  Warning ({migration_name}): {exc}"),
    )
    click.echo("CogOS migrations applied.")


@image.command()
@click.argument("name", default="cogos")
@click.option("--clean", is_flag=True, help="Wipe all tables before loading")
@click.option("--dry-run", is_flag=True, help="Resolve and verify versions, then exit")
@click.option("--executor", "v_executor", default=None, help="Override executor version SHA")
@click.option("--dashboard", "v_dashboard", default=None, help="Override dashboard version SHA")
@click.option("--dashboard-frontend", "v_dashboard_frontend", default=None, help="Override dashboard frontend SHA")
@click.option("--discord-bridge", "v_discord_bridge", default=None, help="Override discord bridge SHA")
@click.option("--lambda", "v_lambda", default=None, help="Override lambda version SHA")
@click.option("--cogos-version", "v_cogos", default=None, help="Override cogos version SHA")
@click.pass_context
def boot(ctx, name, clean, dry_run, v_executor, v_dashboard, v_dashboard_frontend,
         v_discord_bridge, v_lambda, v_cogos):
    """Boot CogOS from an image (default: cogos)."""
    from cogos.image.apply import apply_image
    from cogos.image.spec import load_image
    from cogos.image.versions import (
        ArtifactMissing,
        VersionManifest,
        load_defaults,
        resolve_versions,
        verify_artifacts,
        write_versions_to_filestore,
    )
    from cogos.files.store import FileStore

    image_dir = _resolve_image_dir(name)
    if image_dir is None:
        click.echo(f"Image not found: {name}")
        click.echo("Searched: ./images/, repo root, and bundled package images.")
        return

    # 1. Resolve versions
    if os.environ.get("USE_LOCAL_DB") == "1":
        from cogos.image.versions import KNOWN_COMPONENTS
        defaults = {c: "local" for c in KNOWN_COMPONENTS}
    else:
        defaults = load_defaults(image_dir)
    overrides = {}
    for key, val in [("executor", v_executor), ("dashboard", v_dashboard),
                     ("dashboard_frontend", v_dashboard_frontend),
                     ("discord_bridge", v_discord_bridge),
                     ("lambda", v_lambda), ("cogos", v_cogos)]:
        if val is not None:
            overrides[key] = val

    components = resolve_versions(defaults, overrides)
    click.echo("Resolved versions:")
    for k, v in sorted(components.items()):
        click.echo(f"  {k}: {v}")

    # 2. Verify artifacts (skip for local dev)
    is_local = all(v == "local" for v in components.values())
    if not is_local:
        click.echo("Verifying artifacts...")
        try:
            import boto3
            session = boto3.Session()
            verify_artifacts(
                components,
                ecr_client=session.client("ecr", region_name="us-east-1"),
                s3_client=session.client("s3"),
                artifacts_bucket="cogent-polis-ci-artifacts",
            )
            click.echo("All artifacts verified.")
        except ArtifactMissing as e:
            click.echo(f"ERROR: {e}")
            return

    if dry_run:
        click.echo("Dry run complete.")
        return

    repo = _repo()
    _run_migrations(repo)

    if clean:
        repo.clear_all()
        repo.set_meta("reboot_epoch", "0")
        click.echo("Tables cleaned.")

    # 3. Get epoch from DB
    epoch = repo.reboot_epoch

    # 4. Write versions manifest
    cogent_name = os.environ.get("COGENT_NAME", name)
    manifest = VersionManifest(epoch=epoch, cogent_name=cogent_name, components=components)
    fs = FileStore(repo)
    write_versions_to_filestore(manifest, fs)
    click.echo(f"Wrote versions.json (epoch={epoch})")

    # 5. Continue normal boot
    spec = load_image(image_dir)
    counts = apply_image(spec, repo)

    click.echo(
        f"Boot complete: {counts['capabilities']} capabilities, "
        f"{counts['resources']} resources, {counts['files']} files, "
        f"{counts['processes']} processes, {counts['cron']} cron"
    )


@image.command()
@click.argument("name")
@click.pass_context
def snapshot(ctx: click.Context, name: str):
    """Snapshot running CogOS state into an image."""
    from cogos.image.snapshot import snapshot_image

    output_dir = Path.cwd() / "images" / name
    if output_dir.exists():
        click.echo(f"Image already exists: {output_dir}")
        click.echo("Remove it first or choose a different name.")
        return

    repo = _repo()
    cogent_name = ctx.obj.get("cogent_name")
    snapshot_image(repo, output_dir, cogent_name=cogent_name)
    click.echo(f"Snapshot saved to images/{name}/")


@image.command("list")
def image_list():
    """List available images."""
    from cogos.image.spec import load_image

    search_dirs = [
        Path.cwd() / "images",
        Path(__file__).resolve().parents[3] / "images",
        Path(__file__).resolve().parents[1] / "_bundled_images",
    ]
    seen: set[str] = set()
    found_any = False
    for images_dir in search_dirs:
        if not images_dir.is_dir():
            continue
        for d in sorted(images_dir.iterdir()):
            if not d.is_dir() or d.name.startswith(".") or d.name in seen:
                continue
            seen.add(d.name)
            found_any = True
            try:
                spec = load_image(d)
                click.echo(
                    f"  {d.name:20s}  {len(spec.capabilities)} caps, "
                    f"{len(spec.resources)} resources, {len(spec.processes)} procs, "
                    f"{len(spec.cron_rules)} cron, {len(spec.files)} files"
                )
            except Exception as e:
                click.echo(f"  {d.name:20s}  (error: {e})")
    if not found_any:
        click.echo("No images found.")


def _publish_process_event(repo, process, payload: dict) -> None:
    """Publish a message to the process's implicit channel (process:<name>)."""
    from cogos.db.models import Channel, ChannelMessage, ChannelType
    ch_name = f"process:{process.name}"
    ch = repo.get_channel_by_name(ch_name)
    if not ch:
        ch = Channel(name=ch_name, owner_process=process.id, channel_type=ChannelType.IMPLICIT)
        repo.upsert_channel(ch)
    repo.append_channel_message(ChannelMessage(
        channel=ch.id, sender_process=process.id, payload=payload,
    ))


# ═══════════════════════════════════════════════════════════
# PROCESS commands
# ═══════════════════════════════════════════════════════════

@cogos.group()
def process():
    """Manage processes."""


@process.command("list")
@click.option("--json", "use_json", is_flag=True)
def process_list(use_json: bool):
    """List all processes."""
    repo = _repo()
    procs = repo.list_processes()
    data = [
        {"name": p.name, "mode": p.mode.value, "status": p.status.value,
         "priority": p.priority, "id": str(p.id)}
        for p in procs
    ]
    _output(data, use_json=use_json)


@process.command("get")
@click.argument("name")
@click.option("--json", "use_json", is_flag=True)
def process_get(name: str, use_json: bool):
    """Show a process by name."""
    repo = _repo()
    p = repo.get_process_by_name(name)
    if not p:
        click.echo(f"Process not found: {name}")
        return
    data = p.model_dump(mode="json")
    _output(data, use_json=use_json)


@process.command("create")
@click.argument("name")
@click.option("--mode", type=click.Choice(["daemon", "one_shot"]), default="one_shot")
@click.option("--content", default="")
@click.option("--runner", type=click.Choice(["lambda", "ecs"]), default="lambda")
@click.option("--executor", type=click.Choice(["llm", "python"]), default="llm")
@click.option("--model", default=None)
@click.option("--priority", type=float, default=0.0)
@click.option("--capability", "-cap", multiple=True, help="Capability name to grant (repeatable)")
def process_create(name: str, mode: str, content: str,
                   runner: str, executor: str, model: str | None,
                   priority: float, capability: tuple[str, ...]):
    """Create a new process."""
    from cogos.db.models import Process, ProcessCapability, ProcessMode, ProcessStatus
    repo = _repo()

    p = Process(
        name=name,
        mode=ProcessMode(mode),
        content=content,
        runner=runner,
        executor=executor,
        model=model,
        priority=priority,
        status=ProcessStatus.RUNNABLE,
    )
    pid = repo.upsert_process(p)

    for cap_name in capability:
        cap = repo.get_capability_by_name(cap_name)
        if cap:
            pc = ProcessCapability(process=pid, capability=cap.id, name=cap_name)
            repo.create_process_capability(pc)
            click.echo(f"  granted: {cap_name}")
        else:
            click.echo(f"  warning: capability '{cap_name}' not found")

    click.echo(f"Process created: {name} ({pid})")


@process.command("run")
@click.argument("name")
@click.option("--executor", "executor_override", type=click.Choice(["lambda", "ecs", "local"]),
              default=None, help="Executor backend (default: from process runner field)")
@click.option("--event", default=None, help="JSON event data (e.g. '{\"channel_name\":\"system:tick:hour\"}')")
def process_run(name: str, executor_override: str | None, event: str | None):
    """Trigger a process to run."""
    repo = _repo()
    p = repo.get_process_by_name(name)
    if not p:
        click.echo(f"Process not found: {name}")
        return

    executor = executor_override or p.runner

    if executor == "local":
        from cogos.db.models import ProcessStatus, Run, RunStatus
        from cogos.executor.handler import get_config
        from cogos.runtime.local import run_and_complete

        # Inject cogtainer LLM config into env so executor picks it up
        ctx = click.get_current_context()
        runtime = ctx.obj.get("runtime")
        if runtime and hasattr(runtime, "_entry") and runtime._entry.llm:
            llm = runtime._entry.llm
            os.environ.setdefault("LLM_PROVIDER", llm.provider)
            os.environ.setdefault("DEFAULT_MODEL", llm.model)
            if llm.api_key_env:
                # Ensure the API key env var name is available for the LLM client
                os.environ.setdefault("OPENROUTER_API_KEY", os.environ.get(llm.api_key_env, ""))

        config = get_config()
        repo.update_process_status(p.id, ProcessStatus.RUNNING)

        run = Run(process=p.id, status=RunStatus.RUNNING)
        repo.create_run(run)
        click.echo(f"Starting local run {run.id} for {name}...")

        bedrock = _bedrock_client() if config.llm_provider == "bedrock" else None
        event_data = json.loads(event) if event else {}
        try:
            run = run_and_complete(p, event_data, run, config, repo, bedrock_client=bedrock)
        except Exception as exc:
            import traceback
            click.echo(f"Exception during execution:\n{traceback.format_exc()}")
            run.status = RunStatus.FAILED
            run.error = str(exc)

        # Re-read from DB to get final status (run_and_complete updates DB, not local object)
        db_run = repo.get_run(run.id)
        final_status = db_run.status if db_run else run.status
        click.echo(f"  Run status: {final_status}")
        if final_status == RunStatus.COMPLETED:
            r = db_run or run
            click.echo(f"Run completed in {r.duration_ms or 0}ms")
            click.echo(f"  Tokens: {r.tokens_in} in, {r.tokens_out} out")
            if r.result:
                click.echo(f"  Output: {json.dumps(r.result)[:500]}")
        else:
            error = (db_run.error if db_run else None) or run.error or "(unknown)"
            click.echo(f"Run failed: {error}")
    else:
        # lambda or ecs: mark as runnable for scheduler
        from cogos.db.models import ProcessStatus
        repo.update_process_status(p.id, ProcessStatus.RUNNABLE)
        click.echo(f"Process {name} marked RUNNABLE (executor={executor})")


@process.command("disable")
@click.argument("name")
def process_disable(name: str):
    """Disable a process."""
    from cogos.db.models import ProcessStatus
    repo = _repo()
    p = repo.get_process_by_name(name)
    if not p:
        click.echo(f"Process not found: {name}")
        return
    repo.update_process_status(p.id, ProcessStatus.DISABLED)
    click.echo(f"Process {name} disabled.")


@process.command("load")
@click.argument("file_path", type=click.Path(exists=True))
def process_load(file_path: str):
    """Load process definitions from a YAML or JSON file.

    Each entry should have: name, mode, content, runner, model,
    priority, capabilities (list of capability names), handlers (list of
    channel names).
    """
    from cogos.db.models import (
        Handler as HandlerModel,
    )
    from cogos.db.models import (
        Process as ProcessModel,
    )
    from cogos.db.models import (
        ProcessCapability,
        ProcessMode,
        ProcessStatus,
    )

    fp = Path(file_path).resolve()
    ext = fp.suffix.lower()

    if ext in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            click.echo("PyYAML is required for YAML files. Install with: pip install pyyaml")
            return
        entries = yaml.safe_load(fp.read_text(encoding="utf-8"))
    elif ext == ".json":
        entries = json.loads(fp.read_text(encoding="utf-8"))
    else:
        click.echo(f"Unsupported file format: {ext} (use .yaml, .yml, or .json)")
        return

    if not isinstance(entries, list):
        click.echo("File must contain a list of process definitions.")
        return

    repo = _repo()
    count = 0

    for entry in entries:
        name = entry.get("name")
        if not name:
            click.echo("  Skipping entry without name")
            continue

        mode = ProcessMode(entry.get("mode", "one_shot"))
        p = ProcessModel(
            name=name,
            mode=mode,
            content=entry.get("content", ""),
            runner=entry.get("runner", "lambda"),
            executor=entry.get("executor", "llm"),
            model=entry.get("model"),
            priority=float(entry.get("priority", 0.0)),
            status=ProcessStatus.WAITING if mode == ProcessMode.DAEMON else ProcessStatus.RUNNABLE,
        )
        pid = repo.upsert_process(p)
        click.echo(f"  Process upserted: {name} ({pid})")

        # Bind capabilities
        for cap_name in entry.get("capabilities", []):
            cap = repo.get_capability_by_name(cap_name)
            if not cap:
                click.echo(f"    Warning: capability '{cap_name}' not found")
                continue
            pc = ProcessCapability(process=pid, capability=cap.id, name=cap_name)
            repo.create_process_capability(pc)
            click.echo(f"    Bound capability: {cap_name}")

        # Create handlers (subscribe to channels)
        for ch_name in entry.get("handlers", []):
            from cogos.db.models import Channel, ChannelType
            ch = repo.get_channel_by_name(ch_name)
            if not ch:
                ch = Channel(name=ch_name, channel_type=ChannelType.NAMED)
                repo.upsert_channel(ch)
            h = HandlerModel(process=pid, channel=ch.id, enabled=True, epoch=p.epoch)
            repo.create_handler(h)
            click.echo(f"    Handler added: {ch_name}")

        count += 1

    click.echo(f"Loaded {count} processes from {fp}")


# ═══════════════════════════════════════════════════════════
# HANDLER commands
# ═══════════════════════════════════════════════════════════

@cogos.group()
def handler():
    """Manage channel handlers (process-to-channel subscriptions)."""


@handler.command("list")
@click.option("--process", "process_name", default=None, help="Filter by process name")
@click.option("--json", "use_json", is_flag=True)
def handler_list(process_name: str | None, use_json: bool):
    """List handlers."""
    repo = _repo()
    pid = None
    if process_name:
        p = repo.get_process_by_name(process_name)
        if not p:
            click.echo(f"Process not found: {process_name}")
            return
        pid = p.id
    handlers = repo.list_handlers(process_id=pid)
    # Resolve process names for display
    proc_cache: dict[str, str] = {}
    data = []
    for h in handlers:
        pkey = str(h.process)
        if pkey not in proc_cache:
            proc = repo.get_process(h.process)
            proc_cache[pkey] = proc.name if proc else pkey
        ch_name = None
        if h.channel:
            ch = repo.get_channel(h.channel)
            ch_name = ch.name if ch else str(h.channel)
        data.append({
            "id": str(h.id),
            "process": proc_cache[pkey],
            "channel": ch_name,
            "enabled": h.enabled,
        })
    _output(data, use_json=use_json)


@handler.command("add")
@click.argument("process_name")
@click.argument("channel_name")
def handler_add(process_name: str, channel_name: str):
    """Add a handler subscribing a process to a channel."""
    from cogos.db.models import Channel, ChannelType
    from cogos.db.models import Handler as HandlerModel
    repo = _repo()
    p = repo.get_process_by_name(process_name)
    if not p:
        click.echo(f"Process not found: {process_name}")
        return
    # Ensure the channel exists
    ch = repo.get_channel_by_name(channel_name)
    if not ch:
        ch = Channel(name=channel_name, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
    h = HandlerModel(process=p.id, channel=ch.id, enabled=True, epoch=p.epoch)
    hid = repo.create_handler(h)
    click.echo(f"Handler created: {channel_name} -> {process_name} ({hid})")


@handler.command("remove")
@click.argument("handler_id")
def handler_remove(handler_id: str):
    """Remove a handler by ID."""
    repo = _repo()
    ok = repo.delete_handler(UUID(handler_id))
    if ok:
        click.echo(f"Handler removed: {handler_id}")
    else:
        click.echo(f"Handler not found: {handler_id}")


@handler.command("enable")
@click.argument("handler_id")
def handler_enable(handler_id: str):
    """Enable a handler."""
    repo = _repo()
    hid = UUID(handler_id)
    repo.execute(
        "UPDATE cogos_handler SET enabled = TRUE WHERE id = :id",
        {"id": hid},
    )
    click.echo(f"Handler {handler_id} enabled.")


@handler.command("disable")
@click.argument("handler_id")
def handler_disable(handler_id: str):
    """Disable a handler."""
    repo = _repo()
    hid = UUID(handler_id)
    repo.execute(
        "UPDATE cogos_handler SET enabled = FALSE WHERE id = :id",
        {"id": hid},
    )
    click.echo(f"Handler {handler_id} disabled.")


# ═══════════════════════════════════════════════════════════
# FILE commands
# ═══════════════════════════════════════════════════════════

@cogos.group()
def file():
    """Manage files (versioned store)."""


@file.command("list")
@click.option("--prefix", default=None)
@click.option("--json", "use_json", is_flag=True)
def file_list(prefix: str | None, use_json: bool):
    """List files."""
    repo = _repo()
    files = repo.list_files(prefix=prefix)
    data = [{"key": f.key, "id": str(f.id)} for f in files]
    _output(data, use_json=use_json)


@file.command("get")
@click.argument("key")
def file_get(key: str):
    """Show file content."""
    from cogos.files.store import FileStore
    repo = _repo()
    fs = FileStore(repo)
    content = fs.get_content(key)
    if content is None:
        click.echo(f"File not found: {key}")
        return
    click.echo(content)


@file.command("create")
@click.argument("key")
@click.argument("content")
@click.option("--source", default="human")
def file_create(key: str, content: str, source: str):
    """Create a new file."""
    from cogos.files.store import FileStore
    repo = _repo()
    fs = FileStore(repo)
    f = fs.create(key, content, source=source)
    click.echo(f"File created: {key} ({f.id})")


@file.command("load")
@click.argument("directory", type=click.Path(exists=True))
@click.option("--source", default="human", help="Source tag for file versions")
def file_load(directory: str, source: str):
    """Load .md and .py files from a directory into the file store.

    Scans DIR recursively for .md and .py files. The file key is the
    relative path from DIR (e.g., prompts/scheduler.md). Creates new
    File entries or adds new versions if content changed.
    """
    from cogos.files.store import FileStore
    repo = _repo()
    fs = FileStore(repo)
    dir_path = Path(directory).resolve()
    created = 0
    updated = 0
    unchanged = 0

    for fp in sorted(dir_path.rglob("*")):
        if not fp.is_file():
            continue
        if fp.suffix not in (".md", ".py"):
            continue
        if fp.name.startswith("."):
            continue

        key = str(fp.relative_to(dir_path))
        content = fp.read_text(encoding="utf-8")
        result = fs.upsert(key, content, source=source)

        if result is None:
            unchanged += 1
        elif hasattr(result, "key"):
            # File object returned => newly created
            created += 1
            click.echo(f"  Created: {key}")
        else:
            # FileVersion returned => updated
            updated += 1
            click.echo(f"  Updated: {key}")

    click.echo(f"Files: {created} created, {updated} updated, {unchanged} unchanged")


# ═══════════════════════════════════════════════════════════
# CAPABILITY commands
# ═══════════════════════════════════════════════════════════

@cogos.group()
def capability():
    """Manage capabilities."""


@capability.command("list")
@click.option("--json", "use_json", is_flag=True)
def capability_list(use_json: bool):
    """List capabilities."""
    repo = _repo()
    caps = repo.list_capabilities()
    data = [{"name": c.name, "description": c.description, "enabled": c.enabled, "id": str(c.id)} for c in caps]
    _output(data, use_json=use_json)


@capability.command("get")
@click.argument("name")
@click.option("--json", "use_json", is_flag=True)
def capability_get(name: str, use_json: bool):
    """Show a capability by name."""
    repo = _repo()
    cap = repo.get_capability_by_name(name)
    if not cap:
        click.echo(f"Capability not found: {name}")
        return
    _output(cap.model_dump(mode="json"), use_json=use_json)


@capability.command("enable")
@click.argument("name")
def capability_enable(name: str):
    """Enable a capability."""
    repo = _repo()
    cap = repo.get_capability_by_name(name)
    if not cap:
        click.echo(f"Capability not found: {name}")
        return
    repo.execute(
        "UPDATE cogos_capability SET enabled = TRUE, updated_at = now() WHERE id = :id",
        {"id": cap.id},
    )
    click.echo(f"Capability {name} enabled.")


@capability.command("disable")
@click.argument("name")
def capability_disable(name: str):
    """Disable a capability."""
    repo = _repo()
    cap = repo.get_capability_by_name(name)
    if not cap:
        click.echo(f"Capability not found: {name}")
        return
    repo.execute(
        "UPDATE cogos_capability SET enabled = FALSE, updated_at = now() WHERE id = :id",
        {"id": cap.id},
    )
    click.echo(f"Capability {name} disabled.")


@capability.command("load")
@click.argument("directory", type=click.Path(exists=True))
def capability_load(directory: str):
    """Load capabilities from .py files containing a CAPABILITIES list.

    Each .py file in DIR is scanned for a module-level CAPABILITIES list.
    Each entry should be a dict with keys matching the Capability model
    (name, description, handler, schema, etc.).
    """
    import importlib.util

    from cogos.db.models import Capability as CapabilityModel

    repo = _repo()
    dir_path = Path(directory).resolve()
    count = 0

    for py_file in sorted(dir_path.rglob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            if not spec or not spec.loader:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:
            click.echo(f"  Skip {py_file.name}: {e}")
            continue

        caps_list = getattr(mod, "CAPABILITIES", None)
        if not caps_list or not isinstance(caps_list, list):
            continue

        for cap_dict in caps_list:
            if not isinstance(cap_dict, dict) or "name" not in cap_dict:
                continue
            cap = CapabilityModel(**cap_dict)
            cid = repo.upsert_capability(cap)
            click.echo(f"  Capability upserted: {cap.name} ({cid})")
            count += 1

    click.echo(f"Loaded {count} capabilities from {dir_path}")


# ═══════════════════════════════════════════════════════════
# CHANNEL MESSAGE commands
# ═══════════════════════════════════════════════════════════

@cogos.group()
def channel():
    """Manage channels and messages."""


@channel.command("send")
@click.argument("channel_name")
@click.option("--payload", default="{}")
def channel_send(channel_name: str, payload: str):
    """Send a message to a channel."""
    from cogos.db.models import Channel as ChannelModel
    from cogos.db.models import ChannelMessage, ChannelType
    repo = _repo()
    ch = repo.get_channel_by_name(channel_name)
    if not ch:
        ch = ChannelModel(name=channel_name, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
    msg = ChannelMessage(channel=ch.id, sender_process=None, payload=json.loads(payload))
    mid = repo.append_channel_message(msg)
    click.echo(f"Message sent to {channel_name} ({mid})")


# ═══════════════════════════════════════════════════════════
# RUN commands
# ═══════════════════════════════════════════════════════════

@cogos.group()
def run():
    """View run history."""


@run.command("list")
@click.option("--process", "process_name", default=None)
@click.option("--limit", type=int, default=20)
@click.option("--json", "use_json", is_flag=True)
def run_list(process_name: str | None, limit: int, use_json: bool):
    """List runs."""
    repo = _repo()
    pid = None
    if process_name:
        p = repo.get_process_by_name(process_name)
        if p:
            pid = p.id
    runs = repo.list_runs(process_id=pid, limit=limit)
    if not runs:
        click.echo("(no runs)")
        return

    # Resolve process names
    processes = repo.list_processes()
    proc_names = {p.id: p.name for p in processes}

    data = [
        {
            "id": str(r.id)[:8],
            "process": proc_names.get(r.process, str(r.process)[:8]),
            "status": r.status.value,
            "model": r.model_version or "-",
            "tokens": f"{r.tokens_in}/{r.tokens_out}",
            "cost": f"${r.cost_usd}" if r.cost_usd else "-",
            "duration": f"{r.duration_ms}ms" if r.duration_ms else "-",
            "error": (r.error[:60] + "...") if r.error else None,
            "created_at": str(r.created_at),
        }
        for r in runs
    ]
    # Filter out None error fields for cleaner output
    for d in data:
        if d["error"] is None:
            del d["error"]
    _output(data, use_json=use_json)


@run.command("show")
@click.argument("run_id")
@click.option("--json", "use_json", is_flag=True)
def run_show(run_id: str, use_json: bool):
    """Show run details."""
    from uuid import UUID
    repo = _repo()
    r = repo.get_run(UUID(run_id))
    if not r:
        click.echo(f"Run not found: {run_id}")
        return
    _output(r.model_dump(mode="json"), use_json=use_json)


# ═══════════════════════════════════════════════════════════
# STATUS
# ═══════════════════════════════════════════════════════════

@cogos.command()
def status():
    """Show CogOS status."""
    repo = _repo()
    procs = repo.list_processes()
    click.echo(f"Processes: {len(procs)}")
    for p in procs:
        click.echo(f"  {p.name}: {p.status.value} ({p.mode.value})")

    files = repo.list_files()
    click.echo(f"Files: {len(files)}")

    caps = repo.list_capabilities()
    click.echo(f"Capabilities: {len(caps)}")

    if hasattr(repo, "list_channels"):
        channels = repo.list_channels()
        click.echo(f"Channels: {len(channels)}")
        for ch in channels:
            click.echo(f"  {ch.name} ({ch.channel_type.value})")


# ═══════════════════════════════════════════════════════════
# RESET
# ═══════════════════════════════════════════════════════════

@cogos.command()
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def wipe(yes: bool):
    """Wipe all CogOS tables for a blank slate."""
    if not yes:
        click.confirm("This will DELETE ALL data. Continue?", abort=True)
    repo = _repo()
    repo.clear_all()
    click.echo("All tables cleared.")


@cogos.command()
@click.option("--image", "-i", default="cogos", help="Image name to load (default: cogos)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.option("--full", is_flag=True, help="Wipe ALL data including runtime files (data/, logs/, etc.)")
@click.pass_context
def reload(ctx: click.Context, image: str, yes: bool, full: bool):
    """Reload config and image-owned files, preserving runtime data (data/, logs/, etc.).

    Use --full to wipe everything including runtime data.
    """
    from cogos.image.apply import apply_image
    from cogos.image.spec import image_file_prefixes, load_image

    repo_root = Path(__file__).resolve().parents[3]
    image_dir = repo_root / "images" / image
    if not image_dir.is_dir():
        click.echo(f"Image not found: {image_dir}")
        return

    if not yes:
        if full:
            click.confirm(f"This will DELETE ALL data and reload from '{image}'. Continue?", abort=True)
        else:
            click.confirm(f"This will reload config from '{image}', preserving runtime data. Continue?", abort=True)

    repo = _repo()

    _run_migrations(repo)

    if full:
        # Full wipe — original behaviour
        repo.clear_all()
        click.echo("All tables cleared.")
    else:
        # Selective wipe — clear config/process/message tables, preserve files.
        repo.clear_config()
        click.echo("Config tables cleared.")

        # Delete only files owned by the image
        prefixes = image_file_prefixes(image_dir)
        if prefixes:
            deleted = repo.delete_files_by_prefixes(prefixes)
            click.echo(f"Deleted {deleted} image-owned files (prefixes: {', '.join(prefixes)})")

    # Load image
    spec = load_image(image_dir)
    counts = apply_image(spec, repo)
    click.echo(
        f"Reload complete: {counts['capabilities']} capabilities, "
        f"{counts['resources']} resources, {counts['files']} files, "
        f"{counts['processes']} processes, {counts['cron']} cron"
    )


# ═══════════════════════════════════════════════════════════
# REBOOT
# ═══════════════════════════════════════════════════════════

@cogos.command("reboot")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def reboot_cmd(ctx: click.Context, yes: bool):
    """Kill all processes and restart from init.

    Preserves files, coglets, channels. Clears all processes and runs.
    """
    from cogos.runtime.reboot import reboot as do_reboot

    if not yes:
        click.confirm("This will kill all processes and restart from init. Continue?", abort=True)

    repo = _repo()
    result = do_reboot(repo)
    click.echo(f"Reboot complete: cleared {result['cleared_processes']} processes, init queued")


# ═══════════════════════════════════════════════════════════
# LOCAL EXECUTOR / DISPATCHER
# ═══════════════════════════════════════════════════════════


@cogos.command("start")
@click.option("--daemon", is_flag=True, help="Run in background")
@click.pass_context
def start_cmd(ctx, daemon):
    """Start the local dispatcher."""
    runtime = ctx.obj.get("runtime")
    if runtime is None:
        raise click.ClickException("No cogtainer runtime — configure cogtainers.yml first")
    from cogtainer.local_dispatcher import run_loop
    cogent_name = ctx.obj["cogent_name"]
    repo = runtime.get_repository(cogent_name)
    if daemon:
        import subprocess
        subprocess.Popen([sys.executable, "-m", "cogtainer.local_dispatcher",
                         ctx.obj["cogtainer_name"], cogent_name])
        click.echo("Dispatcher started in background")
    else:
        run_loop(repo, runtime, cogent_name)


# ═══════════════════════════════════════════════════════════
# DASHBOARD commands
# ═══════════════════════════════════════════════════════════

_REPO_ROOT = repo_root()
_FRONTEND_DIR = _REPO_ROOT / "dashboard" / "frontend"
_PID_DIR = Path("/tmp/cogent-dashboard")


def _read_ports() -> tuple[int, int]:
    """Resolve BE/FE ports from env, repo .env, or checkout defaults."""
    return resolve_dashboard_ports(repo_root=_REPO_ROOT)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid(name: str) -> int | None:
    f = _PID_DIR / f"{name}.pid"
    if not f.exists():
        return None
    pid = int(f.read_text().strip())
    if _pid_alive(pid):
        return pid
    f.unlink(missing_ok=True)
    return None


def _write_pid(name: str, pid: int) -> None:
    _PID_DIR.mkdir(parents=True, exist_ok=True)
    (_PID_DIR / f"{name}.pid").write_text(str(pid))


def _kill_pid(name: str) -> bool:
    pid = _read_pid(name)
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    (_PID_DIR / f"{name}.pid").unlink(missing_ok=True)
    return True


def _kill_port(port: int) -> None:
    """Kill any process listening on port."""
    import subprocess as _sp
    try:
        out = _sp.check_output(["lsof", "-ti", f":{port}"], text=True).strip()
        for pid_str in out.splitlines():
            try:
                os.kill(int(pid_str), signal.SIGKILL)
            except OSError:
                pass
    except Exception:
        pass


@cogos.group("dashboard")
def dashboard_group():
    """Manage local dashboard (start/stop/reload)."""


@dashboard_group.command("start")
def dashboard_start():
    """Start the dashboard backend + frontend in the background."""
    import subprocess as _sp

    be_port, fe_port = _read_ports()

    # Check if already running
    be_pid = _read_pid("backend")
    fe_pid = _read_pid("frontend")
    if be_pid and fe_pid:
        click.echo(f"Dashboard already running (backend={be_pid}, frontend={fe_pid})")
        click.echo(f"  http://localhost:{fe_port}")
        return

    # Kill anything on those ports
    _kill_port(be_port)
    _kill_port(fe_port)

    env = {
        **os.environ,
        "DASHBOARD_BE_PORT": str(be_port),
        "DASHBOARD_FE_PORT": str(fe_port),
    }
    apply_local_checkout_env(env, repo_root=_REPO_ROOT)

    # Start backend
    be_proc = _sp.Popen(
        [sys.executable, "-m", "uvicorn", "dashboard.app:app", "--host", "0.0.0.0", "--port", str(be_port)],
        env={**env, "PYTHONPATH": str(_REPO_ROOT / "src")},
        stdout=open("/tmp/cogent-backend.log", "w"),
        stderr=_sp.STDOUT,
        start_new_session=True,
    )
    _write_pid("backend", be_proc.pid)

    # Start frontend
    fe_proc = _sp.Popen(
        ["npx", "next", "dev", "-p", str(fe_port)],
        cwd=str(_FRONTEND_DIR),
        env=env,
        stdout=open("/tmp/cogent-frontend.log", "w"),
        stderr=_sp.STDOUT,
        start_new_session=True,
    )
    _write_pid("frontend", fe_proc.pid)

    click.echo(f"Dashboard started (backend={be_proc.pid}, frontend={fe_proc.pid})")
    click.echo(f"  http://localhost:{fe_port}")
    click.echo("  Logs: /tmp/cogent-backend.log, /tmp/cogent-frontend.log")


@dashboard_group.command("stop")
def dashboard_stop():
    """Stop the dashboard backend + frontend."""
    be_port, fe_port = _read_ports()
    stopped = []
    if _kill_pid("backend"):
        stopped.append("backend")
    if _kill_pid("frontend"):
        stopped.append("frontend")
    # Also kill by port in case PIDs are stale
    _kill_port(be_port)
    _kill_port(fe_port)
    if stopped:
        click.echo(f"Dashboard stopped ({', '.join(stopped)})")
    else:
        click.echo("Dashboard was not running")


@dashboard_group.command("reload")
@click.pass_context
def dashboard_reload(ctx: click.Context):
    """Restart the dashboard (stop + start)."""
    ctx.invoke(dashboard_stop)
    import time as _time
    _time.sleep(1)
    ctx.invoke(dashboard_start)


# ═══════════════════════════════════════════════════════════
# IO commands
# ═══════════════════════════════════════════════════════════

@cogos.group()
def io():
    """Manage I/O integrations (Discord, email, etc.)."""


@io.group()
def discord():
    """Manage the Discord bridge (Fargate service)."""


def _get_ecs_client():
    import boto3
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client("ecs", region_name=region)


def _discord_service_name(cogent_name: str) -> str:
    safe = cogent_name.replace(".", "-")
    return f"cogent-{safe}-discord"


def _discord_cluster_name(cogent_name: str) -> str:
    return "cogent-polis"


def _get_service_status(cogent_name: str) -> dict | None:
    """Get ECS service status for the discord bridge."""
    ecs = _get_ecs_client()
    cluster = _discord_cluster_name(cogent_name)
    service = _discord_service_name(cogent_name)
    try:
        resp = ecs.describe_services(cluster=cluster, services=[service])
        services = resp.get("services", [])
        if not services:
            return None
        svc = services[0]
        return {
            "status": svc.get("status"),
            "desired_count": svc.get("desiredCount", 0),
            "running_count": svc.get("runningCount", 0),
            "pending_count": svc.get("pendingCount", 0),
            "task_definition": svc.get("taskDefinition", ""),
        }
    except Exception:
        return None


@discord.command()
@click.pass_context
def start(ctx: click.Context):
    """Start the Discord bridge Fargate service."""
    cogent_name = ctx.obj["cogent_name"]
    ecs = _get_ecs_client()
    cluster = _discord_cluster_name(cogent_name)
    service = _discord_service_name(cogent_name)

    status = _get_service_status(cogent_name)
    if status and status["desired_count"] > 0:
        click.echo(f"Discord bridge already running ({status['running_count']} tasks)")
        return

    try:
        ecs.update_service(
            cluster=cluster,
            service=service,
            desiredCount=1,
        )
        click.echo(f"Discord bridge starting for {cogent_name}...")
        click.echo(f"  cluster: {cluster}")
        click.echo(f"  service: {service}")
    except Exception as e:
        click.echo(f"Failed to start: {e}", err=True)


@discord.command()
@click.pass_context
def stop(ctx: click.Context):
    """Stop the Discord bridge Fargate service."""
    cogent_name = ctx.obj["cogent_name"]
    ecs = _get_ecs_client()
    cluster = _discord_cluster_name(cogent_name)
    service = _discord_service_name(cogent_name)

    try:
        ecs.update_service(
            cluster=cluster,
            service=service,
            desiredCount=0,
        )
        click.echo(f"Discord bridge stopping for {cogent_name}...")
    except Exception as e:
        click.echo(f"Failed to stop: {e}", err=True)


@discord.command()
@click.pass_context
def restart(ctx: click.Context):
    """Restart the Discord bridge (force new deployment)."""
    cogent_name = ctx.obj["cogent_name"]
    ecs = _get_ecs_client()
    cluster = _discord_cluster_name(cogent_name)
    service = _discord_service_name(cogent_name)

    try:
        ecs.update_service(
            cluster=cluster,
            service=service,
            desiredCount=1,
            forceNewDeployment=True,
        )
        click.echo(f"Discord bridge restarting for {cogent_name}...")
    except Exception as e:
        click.echo(f"Failed to restart: {e}", err=True)


@discord.command("status")
@click.pass_context
def discord_status(ctx: click.Context):
    """Show Discord bridge status."""
    cogent_name = ctx.obj["cogent_name"]
    info = _get_service_status(cogent_name)
    if not info:
        click.echo(f"No Discord bridge service found for {cogent_name}")
        return

    click.echo(f"Discord bridge for {cogent_name}:")
    click.echo(f"  Status:   {info['status']}")
    click.echo(f"  Desired:  {info['desired_count']}")
    click.echo(f"  Running:  {info['running_count']}")
    click.echo(f"  Pending:  {info['pending_count']}")
    click.echo(f"  Task def: {info['task_definition']}")


@discord.command("run-local")
@click.pass_context
def discord_run_local(ctx: click.Context):
    """Run the Discord bridge locally (blocking, for development)."""
    cogent_name = ctx.obj["cogent_name"]
    os.environ.setdefault("COGENT_NAME", cogent_name)

    from cogos.io.discord.bridge import main as bridge_main
    click.echo(f"Starting local Discord bridge for {cogent_name}...")
    bridge_main()


# Memory management CLI
from memory.cli import memory  # noqa: E402

cogos.add_command(memory)


@cogos.command("shell")
@click.pass_context
def shell_cmd(ctx: click.Context):
    """Interactive CogOS shell."""
    from cogos.shell import CogentShell

    cogent_name = ctx.obj.get("cogent_name")
    if not cogent_name:
        raise click.UsageError("No cogent specified. Set COGENT_ID env var or default_cogent in ~/.cogos/config.yml")
    CogentShell(cogent_name).run()


def entry():
    cogos()


if __name__ == "__main__":
    entry()
