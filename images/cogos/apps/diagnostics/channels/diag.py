results = []

def check(name, fn):
    try:
        fn()
        results.append({"name": name, "status": "pass", "ms": 0})
    except Exception as e:
        results.append({"name": name, "status": "fail", "ms": 0, "error": str(e)[:300]})

def test_create_channel():
    channels.create("_diag:pubsub_test")

def test_send_and_read():
    channels.send("_diag:pubsub_test", {"msg": "hello", "seq": 1})
    channels.send("_diag:pubsub_test", {"msg": "world", "seq": 2})
    msgs = channels.read("_diag:pubsub_test", limit=10)
    assert isinstance(msgs, list), "read should return list, got " + str(type(msgs))
    assert len(msgs) >= 2, "expected at least 2 messages, got " + str(len(msgs))

def test_read_limit():
    for i in range(5):
        channels.send("_diag:pubsub_test", {"seq": 100 + i})
    msgs = channels.read("_diag:pubsub_test", limit=3)
    assert isinstance(msgs, list), "read should return list"
    assert len(msgs) <= 3, "limit=3 should return at most 3, got " + str(len(msgs))

def test_read_returns_dicts():
    channels.send("_diag:pubsub_test", {"key": "value"})
    msgs = channels.read("_diag:pubsub_test", limit=1)
    assert len(msgs) >= 1, "expected at least 1 message"
    assert isinstance(msgs[0], dict), "messages should be dicts, got " + str(type(msgs[0]))

def test_send_string_payload():
    channels.send("_diag:pubsub_test", "plain string message")
    msgs = channels.read("_diag:pubsub_test", limit=1)
    assert len(msgs) >= 1, "expected at least 1 message"

def test_send_complex_payload():
    payload = {
        "type": "test",
        "data": {"nested": True, "items": [1, 2, 3]},
        "ts": str(0),
    }
    channels.send("_diag:pubsub_test", payload)
    msgs = channels.read("_diag:pubsub_test", limit=1)
    assert len(msgs) >= 1, "expected at least 1 message"

def test_list_channels():
    ch_list = channels.list()
    assert isinstance(ch_list, list), "list should return list, got " + str(type(ch_list))
    names = [c.get("name", "") if isinstance(c, dict) else str(c) for c in ch_list]
    found = [n for n in names if "_diag:pubsub_test" in n]
    assert len(found) >= 1, "created channel not found in list"

def test_multiple_channels():
    channels.create("_diag:pubsub_a")
    channels.create("_diag:pubsub_b")
    channels.send("_diag:pubsub_a", {"from": "a"})
    channels.send("_diag:pubsub_b", {"from": "b"})
    msgs_a = channels.read("_diag:pubsub_a", limit=5)
    msgs_b = channels.read("_diag:pubsub_b", limit=5)
    assert len(msgs_a) >= 1, "channel a should have messages"
    assert len(msgs_b) >= 1, "channel b should have messages"

def test_spawn_channel_roundtrip():
    channels.create("_diag:spawn:test")
    channels.send("_diag:spawn:test", {"seq": 1, "data": "first"})
    channels.send("_diag:spawn:test", {"seq": 2, "data": "second"})
    msgs = channels.read("_diag:spawn:test", limit=10)
    assert isinstance(msgs, list), "read returned " + str(type(msgs))
    assert len(msgs) >= 2, "expected 2+ msgs, got " + str(len(msgs))

check("create_channel", test_create_channel)
check("send_and_read", test_send_and_read)
check("read_limit", test_read_limit)
check("read_returns_dicts", test_read_returns_dicts)
check("send_string_payload", test_send_string_payload)
check("send_complex_payload", test_send_complex_payload)
check("list_channels", test_list_channels)
check("multiple_channels", test_multiple_channels)
check("spawn_channel_roundtrip", test_spawn_channel_roundtrip)

print(json.dumps(results))
