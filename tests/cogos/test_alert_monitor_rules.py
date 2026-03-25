"""Tests for alert monitor detection rules."""

from datetime import datetime, timedelta, timezone

from cogos.db.models.alert import Alert, AlertSeverity


def _alert(
    alert_type="test:error",
    source="test-proc",
    severity=AlertSeverity.WARNING,
    message="test",
    created_at=None,
    acknowledged_at=None,
    metadata=None,
):
    return Alert(
        severity=severity,
        alert_type=alert_type,
        source=source,
        message=message,
        created_at=created_at or datetime.now(timezone.utc),
        acknowledged_at=acknowledged_at,
        metadata=metadata or {},
    )


def _now():
    return datetime.now(timezone.utc)


# ---- Rule 1: Spam Detection ----

def test_spam_detection_triggers_at_threshold():
    from cogos.lib.alert_rules import detect_spam
    now = _now()
    alerts = [_alert(created_at=now - timedelta(seconds=i)) for i in range(10)]
    actions = detect_spam(alerts, window_seconds=60, threshold=10)
    assert len(actions) == 1
    assert actions[0].kind == "suppress"
    assert actions[0].alert_type == "monitor:spam_detected"


def test_spam_detection_no_trigger_below_threshold():
    from cogos.lib.alert_rules import detect_spam
    now = _now()
    alerts = [_alert(created_at=now - timedelta(seconds=i)) for i in range(5)]
    actions = detect_spam(alerts, window_seconds=60, threshold=10)
    assert len(actions) == 0


def test_spam_detection_groups_by_source_and_type():
    from cogos.lib.alert_rules import detect_spam
    now = _now()
    alerts_a = [_alert(source="a", alert_type="err", created_at=now - timedelta(seconds=i)) for i in range(10)]
    alerts_b = [_alert(source="b", alert_type="err", created_at=now - timedelta(seconds=i)) for i in range(5)]
    actions = detect_spam(alerts_a + alerts_b, window_seconds=60, threshold=10)
    assert len(actions) == 1
    assert actions[0].metadata["source"] == "a"


def test_spam_detection_skips_own_alerts():
    from cogos.lib.alert_rules import detect_spam
    now = _now()
    alerts = [
        _alert(
            source="alert-monitor", alert_type="monitor:spam_detected",
            created_at=now - timedelta(seconds=i),
        )
        for i in range(20)
    ]
    actions = detect_spam(alerts, window_seconds=60, threshold=10)
    assert len(actions) == 0


# ---- Rule 2: Escalating Failure Rate ----

def test_escalating_rate_triggers():
    from cogos.lib.alert_rules import detect_escalating_rate
    now = _now()
    alerts = []
    for minute in range(4):
        for _ in range(2):
            alerts.append(_alert(created_at=now - timedelta(minutes=4 - minute, seconds=30)))
    for i in range(10):
        alerts.append(_alert(created_at=now - timedelta(seconds=i)))
    actions = detect_escalating_rate(alerts, window_seconds=300, buckets=5)
    assert len(actions) == 1
    assert actions[0].kind == "escalate"


def test_escalating_rate_no_trigger_steady():
    from cogos.lib.alert_rules import detect_escalating_rate
    now = _now()
    alerts = []
    for minute in range(5):
        for j in range(3):
            alerts.append(_alert(created_at=now - timedelta(minutes=4 - minute, seconds=j * 10)))
    actions = detect_escalating_rate(alerts, window_seconds=300, buckets=5)
    assert len(actions) == 0


# ---- Rule 3: Critical Signal ----

def test_critical_signal_emergency():
    from cogos.lib.alert_rules import detect_critical_signal
    now = _now()
    alerts = [_alert(severity=AlertSeverity.EMERGENCY, created_at=now)]
    actions = detect_critical_signal(alerts)
    assert len(actions) == 1
    assert actions[0].kind == "escalate"
    assert actions[0].alert_type == "monitor:critical_signal"


def test_critical_signal_ignores_warning():
    from cogos.lib.alert_rules import detect_critical_signal
    now = _now()
    alerts = [_alert(severity=AlertSeverity.WARNING, created_at=now)]
    actions = detect_critical_signal(alerts)
    assert len(actions) == 0


# ---- Rule 4: Unacknowledged Critical ----

def test_unacked_critical_triggers():
    from cogos.lib.alert_rules import detect_unacked_critical
    old = _now() - timedelta(minutes=6)
    alerts = [_alert(severity=AlertSeverity.CRITICAL, created_at=old, acknowledged_at=None)]
    actions = detect_unacked_critical(alerts, stale_minutes=5)
    assert len(actions) == 1
    assert actions[0].kind == "escalate"
    assert actions[0].alert_type == "monitor:unack_escalation"


def test_unacked_critical_skips_acknowledged():
    from cogos.lib.alert_rules import detect_unacked_critical
    old = _now() - timedelta(minutes=6)
    alerts = [_alert(severity=AlertSeverity.CRITICAL, created_at=old, acknowledged_at=_now())]
    actions = detect_unacked_critical(alerts, stale_minutes=5)
    assert len(actions) == 0


def test_unacked_critical_skips_recent():
    from cogos.lib.alert_rules import detect_unacked_critical
    recent = _now() - timedelta(minutes=2)
    alerts = [_alert(severity=AlertSeverity.CRITICAL, created_at=recent, acknowledged_at=None)]
    actions = detect_unacked_critical(alerts, stale_minutes=5)
    assert len(actions) == 0
