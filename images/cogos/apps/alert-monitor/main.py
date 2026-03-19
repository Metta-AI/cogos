# Alert Monitor — daemon Python coglet
# Wakes on each system:alerts message, runs detection rules, dispatches actions.

result = monitor.check()
print(f"Alert monitor: {result.rules_triggered} rules triggered, {result.actions_taken} actions dispatched")
