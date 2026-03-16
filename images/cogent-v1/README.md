# cogent-v1 image

Declarative snapshot of everything needed to initialize a new cogent.

## Structure

```
images/cogent-v1/
├── init/
│   ├── capabilities.py   # built-in capabilities (files, procs, channels, etc.)
│   ├── resources.py       # resource pools (lambda=5, ecs=2)
│   ├── processes.py       # process definitions with handler + capability bindings
│   └── cron.py            # scheduled channel message emitters
├── apps/
│   └── recruiter/         # example recruiting workflow app
└── files/
    └── cogos/
        └── scheduler.md   # scheduler daemon prompt template
```

## What gets synced

1. **Capabilities** — all BUILTIN_CAPABILITIES (files, procs, channels, schemas, resources, secrets, email, scheduler)
2. **Resources** — execution slot pools (lambda=5, ecs=2)
3. **Files** — prompt templates from `files/` and app-specific `apps/*/files/`
4. **Processes** — process definitions with handler + capability bindings
5. **Cron** — scheduled channel message emitters
