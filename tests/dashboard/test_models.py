from dashboard.models import Program, StatusResponse, Trigger


def test_status_response_defaults():
    s = StatusResponse(cogent_name="test")
    assert s.active_sessions == 0
    assert s.cogent_name == "test"


def test_program_from_dict():
    p = Program(name="code-review", runs=10, ok=8, fail=2, total_cost=1.5)
    assert p.name == "code-review"
    assert p.ok == 8


def test_trigger_defaults():
    t = Trigger(id="abc", name="github.push:code-review")
    assert t.enabled is True
    assert t.fired_1h == 0
