"""Tests for the Discord cog image registration."""

from pathlib import Path

from cogos.image.spec import load_image


class TestDiscordCogImage:
    def test_discord_cog_registered(self):
        spec = load_image(Path("images/cogos"))
        cog_names = {c["name"] for c in spec.cogs}
        assert "discord" in cog_names

    def test_discord_cog_config(self):
        spec = load_image(Path("images/cogos"))
        discord_cog = next(c for c in spec.cogs if c["name"] == "discord")
        config = discord_cog["config"]
        assert config["mode"] == "daemon"
        assert config["executor"] == "python"

    def test_discord_cog_has_handlers(self):
        spec = load_image(Path("images/cogos"))
        discord_cog = next(c for c in spec.cogs if c["name"] == "discord")
        handlers = discord_cog["config"]["handlers"]
        assert "discord-cog:review" in handlers
        assert "system:tick:hour" in handlers

    def test_discord_cog_has_capabilities(self):
        spec = load_image(Path("images/cogos"))
        discord_cog = next(c for c in spec.cogs if c["name"] == "discord")
        caps = discord_cog["config"]["capabilities"]
        cap_names = [c if isinstance(c, str) else c["name"] for c in caps]
        assert "discord" in cap_names

    def test_discord_cog_has_handler_coglet(self):
        """Discord cog should have a 'handler' coglet subdirectory."""
        spec = load_image(Path("images/cogos"))
        discord_cog = next(c for c in spec.cogs if c["name"] == "discord")
        assert "handler" in discord_cog["coglets"]

    def test_no_static_discord_handle_message(self):
        """The old discord-handle-message process should not be in init.py."""
        init_py = Path("images/cogos/cogos/init.py").read_text()
        assert "discord-handle-message" not in init_py

    def test_no_legacy_scheduler_spawn_in_init(self):
        """Dispatcher Lambda owns scheduling; init.py must not spawn a scheduler daemon."""
        init_py = Path("images/cogos/cogos/init.py").read_text()
        assert 'procs.spawn("scheduler"' not in init_py

    def test_init_reads_cog_manifests(self):
        """Init reads _boot/cog_manifests.json and spawns cog processes."""
        init_py = Path("images/cogos/cogos/init.py").read_text()
        assert "_boot/cog_manifests.json" in init_py
        assert "_spawn_cog" in init_py

    def test_init_kicks_discord_review_after_boot(self):
        """Init sends discord-cog:review so discord can spawn its handler."""
        init_py = Path("images/cogos/cogos/init.py").read_text()
        assert 'channels.send("discord-cog:review"' in init_py

    def test_discord_orchestrator_spawns_handler_if_missing(self):
        """Discord orchestrator should spawn handler when it doesn't exist."""
        discord_py = Path("images/cogos/apps/discord/main.py").read_text()
        assert 'procs.spawn("discord/handler"' in discord_py

    def test_discord_orchestrator_has_web_capability(self):
        """Discord orchestrator needs web to delegate to handler."""
        spec = load_image(Path("images/cogos"))
        discord_cog = next(c for c in spec.cogs if c["name"] == "discord")
        caps = discord_cog["config"]["capabilities"]
        cap_names = [c if isinstance(c, str) else c["name"] for c in caps]
        assert "web" in cap_names

    def test_discord_handler_prompt_uses_web_url_helper(self):
        prompt = Path("images/cogos/apps/discord/handler/main.md").read_text()
        assert "web.url(path)" in prompt

    def test_discord_handler_cog_does_not_include_cogent_capability(self):
        """The discord handler cog should not request the 'cogent' capability."""
        import importlib
        import importlib.util

        cog_path = Path("images/cogos/apps/discord/handler/cog.py")
        spec = importlib.util.spec_from_file_location("handler_cog", cog_path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert "cogent" not in mod.config.capabilities

    def test_discord_handler_cog_capabilities_list(self):
        """The discord handler should have expected capabilities without 'cogent'."""
        import importlib
        import importlib.util

        cog_path = Path("images/cogos/apps/discord/handler/cog.py")
        spec = importlib.util.spec_from_file_location("handler_cog", cog_path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        caps = mod.config.capabilities
        assert "discord" in caps
        assert "channels" in caps
        assert "procs" not in caps  # handler doesn't need process management
        assert "image" in caps
        assert "cogent" not in caps

    def test_init_process_does_not_request_scheduler_capability(self):
        """The init process should not request the obsolete scheduler capability."""
        spec = load_image(Path("images/cogos"))
        init_proc = next(p for p in spec.processes if p["name"] == "init")
        assert "scheduler" not in init_proc["capabilities"]


class TestDiscordCogApply:
    def test_apply_does_not_create_cog_processes(self, tmp_path):
        """Cog processes are now spawned by init.py, not apply_image."""
        from cogos.db.sqlite_repository import SqliteRepository
        from cogos.image.apply import apply_image

        spec = load_image(Path("images/cogos"))
        repo = SqliteRepository(str(tmp_path))
        apply_image(spec, repo)

        procs = repo.list_processes(limit=100)
        proc_names = {p.name for p in procs}
        assert "discord" not in proc_names, f"'discord' should not be created by apply_image, got: {proc_names}"
        assert "discord/handler" not in proc_names

    def test_apply_writes_cog_manifests(self, tmp_path):
        """apply_image writes _boot/cog_manifests.json for init.py to read."""
        import json

        from cogos.db.sqlite_repository import SqliteRepository
        from cogos.files.store import FileStore
        from cogos.image.apply import apply_image

        spec = load_image(Path("images/cogos"))
        repo = SqliteRepository(str(tmp_path))
        apply_image(spec, repo)

        store = FileStore(repo)
        raw = store.get_content("mnt/boot/_boot/cog_manifests.json")
        assert raw is not None
        manifests = json.loads(raw)
        names = {entry["name"] for entry in manifests}
        assert "discord" in names
        assert "newsfromthefront" in names
        assert "recruiter" in names
        assert "website" in names

        discord_entry = next(e for e in manifests if e["name"] == "discord")
        assert discord_entry["config"]["mode"] == "daemon"
        assert "discord-cog:review" in discord_entry["config"]["handlers"]
        assert "handler" in discord_entry["coglets"]
