# Daily report at 14:00 UTC (6am Pacific) on weekdays
add_cron("0 14 * * 1-5", event_type="pointy:daily-tick", payload={}, enabled=True)
