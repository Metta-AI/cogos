# Only the init process is declared statically.
# All other processes are spawned by init at runtime.

add_process(
    "init",
    mode="daemon",
    content="@{mnt/boot/cogos/init.py}",
    executor="python",
    required_tags=[],
    priority=100.0,
    capabilities=[
        "me", "procs", "fs_dir", "file", "discord", "channels",
        "secrets", "alerts", "cogent", "history",
        "blob", "image",
        # Delegatable to supervisor → helpers:
        "asana", "email", "github", "google_docs", "web_search", "web_fetch", "web",
        "cog_registry", "coglet_runtime",
    ],
)
