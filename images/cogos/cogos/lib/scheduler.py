# CogOS scheduler tick — Python executor (zero LLM tokens).
#
# Runs every minute via system:tick:minute. Executes all four scheduler
# steps deterministically with no LLM reasoning needed.

r1 = scheduler.match_messages()
print(f"Matched {r1.deliveries_created} deliveries")

r2 = scheduler.unblock_processes()
print(f"Unblocked {r2.unblocked_count} processes")

r3 = scheduler.select_processes(slots=3)
print(f"Selected {len(r3.selected)} processes")

for proc in r3.selected:
    r4 = scheduler.dispatch_process(process_id=proc.id)
    print(f"Dispatched {r4.process_name} -> run {r4.run_id}")

print(f"Tick done: {r1.deliveries_created} matched, {r2.unblocked_count} unblocked, {len(r3.selected)} dispatched")
