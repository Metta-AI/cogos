"""Tests for the Discord cog image registration."""

from pathlib import Path

from cogos.image.spec import load_image


class TestDiscordCogImage:
    def test_discord_cog_registered(self):
        spec = load_image(Path("images/cogent-v1"))
        cog_names = {c["name"] for c in spec.cogs}
        assert "discord" in cog_names

    def test_discord_cog_has_default_coglet(self):
        spec = load_image(Path("images/cogent-v1"))
        discord_cog = next(c for c in spec.cogs if c["name"] == "discord")
        default = discord_cog["default_coglet"]
        assert default is not None
        assert default["entrypoint"] == "main.py"
        assert default["mode"] == "daemon"

    def test_discord_cog_has_handlers(self):
        spec = load_image(Path("images/cogent-v1"))
        discord_cog = next(c for c in spec.cogs if c["name"] == "discord")
        handlers = discord_cog["default_coglet"]["handlers"]
        assert "discord-cog:review" in handlers
        assert "system:tick:hour" in handlers

    def test_discord_cog_has_cog_capability(self):
        spec = load_image(Path("images/cogent-v1"))
        discord_cog = next(c for c in spec.cogs if c["name"] == "discord")
        caps = discord_cog["default_coglet"]["capabilities"]
        assert "cog" in caps

    def test_no_static_discord_handle_message(self):
        """The old discord-handle-message process should not be in init.py."""
        init_py = Path("images/cogent-v1/cogos/init.py").read_text()
        assert "discord-handle-message" not in init_py

    def test_no_legacy_scheduler_spawn_in_init(self):
        """Dispatcher Lambda owns scheduling; init.py must not spawn a scheduler daemon."""
        init_py = Path("images/cogent-v1/cogos/init.py").read_text()
        assert 'procs.spawn("scheduler"' not in init_py

    def test_init_spawns_cog_processes_from_manifest(self):
        """Init reads _boot/cog_processes.json and spawns top-level cog processes."""
        init_py = Path("images/cogent-v1/cogos/init.py").read_text()
        assert "_boot/cog_processes.json" in init_py
        assert "_spawn_from_spec" in init_py

    def test_init_kicks_discord_review_after_boot(self):
        """Init sends discord-cog:review so discord can spawn its handler."""
        init_py = Path("images/cogent-v1/cogos/init.py").read_text()
        assert 'channels.send("discord-cog:review"' in init_py

    def test_discord_orchestrator_spawns_handler_if_missing(self):
        """Discord orchestrator should spawn handler when it doesn't exist."""
        discord_py = Path("images/cogent-v1/apps/discord/discord.py").read_text()
        assert 'procs.spawn("discord/handler"' in discord_py

    def test_discord_orchestrator_has_web_capability(self):
        """Discord orchestrator needs web to delegate to handler."""
        spec = load_image(Path("images/cogent-v1"))
        discord_cog = next(c for c in spec.cogs if c["name"] == "discord")
        caps = discord_cog["default_coglet"]["capabilities"]
        cap_names = [c if isinstance(c, str) else c["name"] for c in caps]
        assert "web" in cap_names

    def test_discord_handler_prompt_uses_web_url_helper(self):
        prompt = Path("images/cogent-v1/apps/discord/handler/main.md").read_text()
        assert "web.url(path)" in prompt
        assert "Do NOT invent or guess the domain or route." in prompt

    def test_init_process_does_not_request_scheduler_capability(self):
        """The init process should not request the obsolete scheduler capability."""
        spec = load_image(Path("images/cogent-v1"))
        init_proc = next(p for p in spec.processes if p["name"] == "init")
        assert "scheduler" not in init_proc["capabilities"]

    def test_init_holds_cog_capabilities_for_delegation(self):
        """Init must hold cog and coglet_runtime to delegate them to cog processes."""
        spec = load_image(Path("images/cogent-v1"))
        init_proc = next(p for p in spec.processes if p["name"] == "init")
        assert "cog" in init_proc["capabilities"]
        assert "coglet_runtime" in init_proc["capabilities"]


class TestDiscordCogApply:
    def test_apply_does_not_create_cog_processes(self, tmp_path):
        """Cog processes are now spawned by init.py, not apply_image."""
        from cogos.db.local_repository import LocalRepository
        from cogos.image.apply import apply_image

        spec = load_image(Path("images/cogent-v1"))
        repo = LocalRepository(str(tmp_path))
        apply_image(spec, repo)

        procs = repo.list_processes(limit=100)
        proc_names = {p.name for p in procs}
        assert "discord" not in proc_names, f"'discord' should not be created by apply_image, got: {proc_names}"
        assert "discord/handler" not in proc_names

    def test_apply_creates_discord_coglet(self, tmp_path):
        from cogos.cog import load_coglet_meta
        from cogos.db.local_repository import LocalRepository
        from cogos.files.store import FileStore
        from cogos.image.apply import apply_image

        spec = load_image(Path("images/cogent-v1"))
        repo = LocalRepository(str(tmp_path))
        apply_image(spec, repo)

        store = FileStore(repo)
        meta = load_coglet_meta(store, "discord", "discord")
        assert meta is not None
        assert meta.entrypoint == "main.py"
        assert meta.mode == "daemon"

    def test_apply_writes_boot_manifest(self, tmp_path):
        """apply_image writes _boot/cog_processes.json for init.py to read."""
        import json

        from cogos.db.local_repository import LocalRepository
        from cogos.files.store import FileStore
        from cogos.image.apply import apply_image

        spec = load_image(Path("images/cogent-v1"))
        repo = LocalRepository(str(tmp_path))
        apply_image(spec, repo)

        store = FileStore(repo)
        raw = store.get_content("_boot/cog_processes.json")
        assert raw is not None
        manifest = json.loads(raw)
        names = {entry["name"] for entry in manifest}
        assert "discord" in names
        assert "newsfromthefront" in names
        assert "recruiter" in names
        assert "website" in names

        discord_entry = next(e for e in manifest if e["name"] == "discord")
        assert discord_entry["mode"] == "daemon"
        assert "discord-cog:review" in discord_entry["handlers"]
        child_names = {c["name"] for c in discord_entry["children"]}
        assert "discord/handler" in child_names
