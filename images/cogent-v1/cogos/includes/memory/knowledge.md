# Memory Policy: Knowledge

You maintain a living knowledge base in `data/knowledge.md`. This is everything you know — facts, preferences, patterns, decisions. Unlike a log, entries are updated in place and organized by topic, not time.

## On Startup

Read `data/knowledge.md`. Use it to inform all of your work — it contains accumulated learnings from previous runs.

## During Execution

When you learn something durable — a user preference, a confirmed pattern, a decision and its rationale, a fact you'll need again:

1. Read `data/knowledge.md`.
2. Check if this knowledge already exists:
   - Already there and still accurate — skip.
   - Already there but outdated — update in place.
   - New — append under the appropriate section.
3. Write the updated file.

Don't record transient information (use `session` or `scratchpad` for that). Knowledge entries should be things that are true across runs.

## Organization

Structure `data/knowledge.md` by topic using H2 headers:

```
## Preferences
## Patterns
## Decisions
## Facts
```

Add sections as needed for your domain. Keep entries concise — one to two lines each.

## Maintenance

If `data/knowledge.md` exceeds 300 lines, review for:
- Redundant entries — merge them.
- Stale entries — remove if no longer true.
- Entries that could be more concise — tighten the wording.

## Bootstrap

If `data/knowledge.md` doesn't exist, create it with a header and empty topic sections relevant to your domain:

```
# Knowledge

## Preferences

## Patterns

## Decisions

## Facts
```
