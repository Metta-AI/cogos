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

    def test_discord_handler_prompt_uses_web_url_helper(self):
        prompt = Path("images/cogent-v1/apps/discord/handler/main.md").read_text()
        assert "web.url(path)" in prompt
        assert "Do NOT invent or guess the domain or route." in prompt

    def test_init_process_does_not_request_scheduler_capability(self):
        """The init process should not request the obsolete scheduler capability."""
        spec = load_image(Path("images/cogent-v1"))
        init_proc = next(p for p in spec.processes if p["name"] == "init")
        assert "scheduler" not in init_proc["capabilities"]


class TestDiscordCogApply:
    def test_apply_creates_discord_process(self, tmp_path):
        from cogos.image.apply import apply_image
        from cogos.db.local_repository import LocalRepository

        spec = load_image(Path("images/cogent-v1"))
        repo = LocalRepository(str(tmp_path))
        apply_image(spec, repo)

        procs = repo.list_processes(limit=100)
        proc_names = {p.name for p in procs}
        assert "discord" in proc_names, f"Expected 'discord' process, got: {proc_names}"

    def test_apply_creates_discord_coglet(self, tmp_path):
        from cogos.image.apply import apply_image
        from cogos.db.local_repository import LocalRepository
        from cogos.cog import load_coglet_meta
        from cogos.files.store import FileStore

        spec = load_image(Path("images/cogent-v1"))
        repo = LocalRepository(str(tmp_path))
        apply_image(spec, repo)

        store = FileStore(repo)
        meta = load_coglet_meta(store, "discord", "discord")
        assert meta is not None
        assert meta.entrypoint == "main.py"
        assert meta.mode == "daemon"

    def test_apply_creates_discord_handler(self, tmp_path):
        """Handler child coglet is created at boot, not at runtime."""
        from cogos.image.apply import apply_image
        from cogos.db.local_repository import LocalRepository

        spec = load_image(Path("images/cogent-v1"))
        repo = LocalRepository(str(tmp_path))
        apply_image(spec, repo)

        procs = repo.list_processes(limit=100)
        proc_names = {p.name for p in procs}
        assert "discord/handler" in proc_names, f"Expected 'discord/handler', got: {proc_names}"
        handler = next(p for p in procs if p.name == "discord/handler")
        assert handler.model == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        assert handler.mode.value == "daemon"
