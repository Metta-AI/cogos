# Cron and Scheduling

CogOS supports scheduled messaging through cron rules and system tick channels.

## Cron rules

Cron rules send messages to channels on a schedule. They use standard cron expressions:

```python
add_cron("* * * * *", channel="system:tick:minute")
add_cron("0 * * * *", channel="system:tick:hour")
add_cron("0 9 * * 1", channel="weekly:monday-standup")
```

Each cron rule has:
- `expression` — standard cron syntax (minute hour day month weekday)
- `channel` — the channel to send a message to when the rule fires
- `payload` — optional JSON payload attached to the message
- `enabled` — toggle on/off without deleting

## System tick channels

The dispatcher generates virtual tick messages every minute:
- `system:tick:minute` — every invocation
- `system:tick:hour` — when minute == 0

These are NOT written to the channel log — they're synthetic messages that trigger handler matching.

## How scheduling works

1. Cron rules fire and send messages to channels
2. The scheduler's `match_channel_messages()` scans undelivered messages
3. Messages are matched against handler channel subscriptions on daemon processes
4. Matching processes transition from WAITING to RUNNABLE
5. `select_processes()` picks processes to run based on priority
6. `dispatch_process()` transitions them to RUNNING and invokes the runner

## Scheduler daemon

The scheduler is itself a daemon process. It runs every minute (triggered by the dispatcher directly, not via cron). Its tick sequence:

1. `scheduler.match_channel_messages()` — create deliveries, wake waiting processes
2. `scheduler.unblock_processes()` — check blocked processes
3. `scheduler.select_processes(slots=3)` — softmax sample from runnable
4. `scheduler.dispatch_process(id)` — for each, create run and invoke

## Periodic tasks

To run something periodically, create a daemon that subscribes to the appropriate tick channel:

```python
add_process(
    "hourly-report",
    mode="daemon",
    handlers=["system:tick:hour"],
    capabilities=["channels", "files", "email"],
    ...
)
```

Or define a custom cron rule:

```python
add_cron("*/15 * * * *", channel="check:health")

add_process(
    "health-checker",
    mode="daemon",
    handlers=["check:health"],
    ...
)
```
