# Daily research run at 08:00 UTC.
add_cron("0 8 * * *", event_type="newsfromthefront:tick", payload={}, enabled=True)
