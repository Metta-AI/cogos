# File Layout

This is how your file store is organized. Use `dir.list(prefix)` to explore.

```
whoami/                     Who you are
  index.md                    Identity, role, principles
  softmax.md                  Organization context

cogos/                      CogOS system files
  docs/                       How CogOS works (you are here)
    layout.md                   This file — file organization guide
    sandbox.md                  Sandbox execution model
    capabilities.md             Capability system and scoping
    fs.md                       File store — versioned key-value storage
    channels.md                  Channel system — typed message streams
    process.md                  Process lifecycle and modes
    cron.md                     Cron and scheduled events
  includes/                   Per-subsystem method references (auto-injected)
    code_mode.md                How to use search() and run_code()
    files.md                    files/dir/file_version API
    channels.md                  channels API
    procs.md                    procs API
    discord.md                  discord API
    email.md                    email API
  lib/                        Process implementations
    scheduler.md                Scheduler daemon prompt

apps/                       Installed applications
  {app}/                      Each app gets its own namespace
    prompts/                    Process prompt templates
    ...                         App-specific files (config, data, etc.)
```

## How files work

- **docs/** — reference documentation. Read these to understand CogOS concepts.
- **includes/** — method references and examples. These are auto-injected into every process's system prompt, so you always have API docs available.
- **lib/** — process prompts. Each daemon's instructions live here.
- **whoami/** — your identity and organizational context.

## Self-modification

You can read and write any file you have capability for. CogOS is designed for self-modifying applications:

```python
# Read your own docs
layout = files.read("cogos/docs/layout.md")
print(layout.content)

# Update a process prompt
files.write("cogos/lib/scheduler.md", new_scheduler_prompt)

# Add a new include
files.write("cogos/includes/my_tool.md", "# My Tool\n...")
```

Every write creates a new version. Old versions are preserved and accessible via `file_version`.
