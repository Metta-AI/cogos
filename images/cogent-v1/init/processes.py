# Only the init process is declared statically.
# All other processes are spawned by init at runtime.

add_process(
    "init",
    mode="one_shot",
    content="@{cogos/init.py}",
    executor="python",
    runner="lambda",
    priority=200.0,
    capabilities=[
        "me", "procs", "dir", "file", "discord", "channels",
        "secrets", "stdlib", "coglet_factory", "coglet", "alerts",
        "blob", "image",
        # Delegatable to supervisor → helpers:
        "asana", "email", "github", "web_search", "web_fetch", "web",
    ],
)
