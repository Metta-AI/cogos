from dashboard.models import StatusResponse, Program, Event, Trigger


def test_status_response_defaults():
    s = StatusResponse(cogent_id="test")
    assert s.active_sessions == 0
    assert s.cogent_id == "test"


def test_program_from_dict():
    p = Program(name="code-review", runs=10, ok=8, fail=2, total_cost=1.5)
    assert p.name == "code-review"
    assert p.ok == 8


def test_event_accepts_int_or_str_id():
    e1 = Event(id=42, event_type="test")
    e2 = Event(id="abc-123", event_type="test")
    assert e1.id == 42
    assert e2.id == "abc-123"


def test_trigger_defaults():
    t = Trigger(id="abc", name="github.push:code-review")
    assert t.enabled is True
    assert t.fired_1h == 0
