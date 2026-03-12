# Cron and Scheduling

CogOS supports scheduled events through cron rules and system tick events.

## Cron rules

Cron rules emit events on a schedule. They use standard cron expressions:

```python
add_cron("* * * * *", event_type="system:tick:minute")
add_cron("0 * * * *", event_type="system:tick:hour")
add_cron("0 9 * * 1", event_type="weekly:monday-standup")
```

Each cron rule has:
- `expression` — standard cron syntax (minute hour day month weekday)
- `event_type` — the event to emit when the rule fires
- `payload` — optional JSON payload attached to the event
- `enabled` — toggle on/off without deleting

## System tick events

The dispatcher generates virtual tick events every minute:
- `system:tick:minute` — every invocation
- `system:tick:hour` — when minute == 0

These are NOT written to the event log — they're synthetic events that trigger handler matching.

## How scheduling works

1. Cron rules fire and emit events into the event log
2. The scheduler's `match_events()` scans undelivered events
3. Events are matched against handler patterns on daemon processes
4. Matching processes transition from WAITING to RUNNABLE
5. `select_processes()` picks processes to run based on priority
6. `dispatch_process()` transitions them to RUNNING and invokes the runner

## Scheduler daemon

The scheduler is itself a daemon process. It runs every minute (triggered by the dispatcher directly, not via cron). Its tick sequence:

1. `scheduler.match_events()` — create deliveries, wake waiting processes
2. `scheduler.unblock_processes()` — check blocked processes
3. `scheduler.select_processes(slots=3)` — softmax sample from runnable
4. `scheduler.dispatch_process(id)` — for each, create run and invoke

## Periodic tasks

To run something periodically, create a daemon with a handler for the appropriate tick event:

```python
add_process(
    "hourly-report",
    mode="daemon",
    handlers=["system:tick:hour"],
    capabilities=["events", "files", "email"],
    ...
)
```

Or define a custom cron rule:

```python
add_cron("*/15 * * * *", event_type="check:health")

add_process(
    "health-checker",
    mode="daemon",
    handlers=["check:health"],
    ...
)
```
