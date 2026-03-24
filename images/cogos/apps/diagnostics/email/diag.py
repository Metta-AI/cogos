checks = []

try:
    if email is None:
        checks.append({"name": "email_wired", "status": "fail", "ms": 0, "error": "email capability is None"})
    else:
        has_methods = len([m for m in dir(email) if not m.startswith("_")]) > 0
        if has_methods:
            checks.append({"name": "email_wired", "status": "pass", "ms": 0})
        else:
            checks.append({"name": "email_wired", "status": "fail", "ms": 0, "error": "no methods found on email capability"})

        addr = email.addresses()
        if addr and "@" in addr:
            checks.append({"name": "email_address", "status": "pass", "ms": 0})
        else:
            checks.append({"name": "email_address", "status": "fail", "ms": 0, "error": "no valid address: " + repr(addr)})

        try:
            msgs = email.receive(limit=5)
            if isinstance(msgs, list):
                checks.append({"name": "email_receive", "status": "pass", "ms": 0})
            else:
                checks.append({"name": "email_receive", "status": "fail", "ms": 0, "error": "receive returned " + str(type(msgs))})
        except Exception as e:
            checks.append({"name": "email_receive", "status": "fail", "ms": 0, "error": str(e)[:300]})

except Exception as e:
    checks.append({"name": "email_wired", "status": "fail", "ms": 0, "error": str(e)[:300]})

print(json.dumps(checks))
