# Memory Policy: Ledger

You maintain a structured event log in `data/ledger.jsonl`. This is your audit trail — exact records of what happened, queryable and archivable. Entries are never summarized or modified.

## On Startup

Read `data/ledger.jsonl`. If the file is large, read the last 100 lines for recent context.

## During Execution

After each recordable event, append a JSON line to `data/ledger.jsonl`:

```json
{"t": "YYYY-MM-DDTHH:MM:SSZ", "type": "event_type", "summary": "what happened", ...}
```

Keep entries flat and consistent — same fields for the same event type. Include enough context that each line is self-contained and useful without reading surrounding entries.

## Maintenance

After appending, if `data/ledger.jsonl` exceeds 500 lines:

1. Read the first 400 lines (the older entries).
2. Write them to `data/ledger.{YYYY-MM-DD}.jsonl` as an archive.
3. Rewrite `data/ledger.jsonl` with only the remaining recent lines.

## Querying

When you need historical data, list `data/` for archived ledger files and read them as needed. Each archive filename contains its rotation date.

## Bootstrap

If `data/ledger.jsonl` doesn't exist, create it empty.
