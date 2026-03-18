# Diagnostic: scheduler/handler_wakeup.py
# Creates a channel, spawns a daemon subscribed to it, sends a message,
# runs match_messages(), and checks the process becomes runnable.

import time

checks = []


def check(name, fn):
    t0 = time.time()
    try:
        fn()
        ms = int((time.time() - t0) * 1000)
        checks.append({"name": name, "status": "pass", "ms": ms})
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        checks.append({"name": name, "status": "fail", "ms": ms, "error": str(e)})


CHAN_NAME = "diag_wakeup_test"


# ── create channel ───────────────────────────────────────────

def test_create_channel():
    channels.create(CHAN_NAME)

check("create_channel", test_create_channel)


# ── spawn daemon subscribed to channel ───────────────────────

daemon_handle = None

def test_spawn_daemon():
    global daemon_handle
    handle = procs.spawn(
        "diag_wakeup_daemon",
        mode="daemon",
        content="# daemon that waits for messages\nimport time\ntime.sleep(30)\n",
        executor="python",
        capabilities={"channels": channels, "me": me, "stdlib": stdlib},
        subscribe=[CHAN_NAME],
    )
    if hasattr(handle, "error"):
        raise Exception("spawn error: " + str(handle.error))
    daemon_handle = handle

check("spawn_daemon", test_spawn_daemon)


# ── send message on channel ──────────────────────────────────

def test_send_message():
    channels.send(CHAN_NAME, {"type": "wakeup", "ts": stdlib.time_iso()})

check("send_message", test_send_message)


# ── match_messages wakes the process ─────────────────────────

def test_match_and_select():
    matched = scheduler.match_messages()
    if not isinstance(matched, int):
        raise Exception("match_messages() should return int, got: " + str(type(matched)))
    # After matching, try to select runnable processes
    selected = scheduler.select_processes(slots=5)
    if not isinstance(selected, list):
        raise Exception("select_processes() should return list, got: " + str(type(selected)))

check("match_and_select", test_match_and_select)


# ── verify channel has the message ───────────────────────────

def test_channel_read():
    msgs = channels.read(CHAN_NAME, limit=5)
    if not isinstance(msgs, list):
        raise Exception("channels.read() should return list, got: " + str(type(msgs)))
    found = False
    for msg in msgs:
        if isinstance(msg, dict) and msg.get("type") == "wakeup":
            found = True
    if not found:
        raise Exception("wakeup message not found in channel")

check("channel_read", test_channel_read)


print(json.dumps(checks))
