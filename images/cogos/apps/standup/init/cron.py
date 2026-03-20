# Daily standup report at 09:00 UTC (morning for US teams).
add_cron("0 9 * * *", event_type="standup:tick", payload={}, enabled=True)
