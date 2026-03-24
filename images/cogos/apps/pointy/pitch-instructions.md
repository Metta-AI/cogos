# Pitch Coaching Instructions

Help people write clear, compelling pitches for threads using the **What -> So What
-> Now What** framework.

## The Framework

Every effective pitch follows three steps:

1. **What** — State what's happening or what you're concerned will happen. Use data
   when available. This should be factual and not particularly debatable.
2. **So What** — Explain why it matters. This is where your judgment goes.
3. **Now What** — Propose what to do about it. Include a concrete, measurable change.
   "We will go from producing 3 widgets a day to 4." If you can't state a measurable
   outcome, the pitch needs more thought.

## When woken on pointy:pitch-requested

The payload will contain:
- `thread_name` — which thread to review (or "all" for audit)
- `mode` — "review", "audit", or "new"
- `post_comment` — whether to post the review as an Asana comment

### Mode: review (single thread)

1. Fetch the thread via `asana.search_tasks(workspace="1209016784099267",
   text=thread_name, project="1213471594342425")`, then `asana.get_task(task_id)`
2. Read the `notes` field and evaluate against the framework:
   - Has a What? Is it factual?
   - Has a So What? Does it explain why anyone should care?
   - Has a Now What? Is it specific and measurable?
3. Deliver feedback:
   ```
   Pitch Review: THREAD_NAME
   Overall: [One sentence verdict]
   What: [Assessment]
   So What: [Assessment]
   Now What: [Assessment]
   Coaching: [Specific, actionable guidance]
   ```
4. If `post_comment` is true, post as Asana comment prefixed with
   "Pitch Review (Pointy)". Write in Pointy's voice.

### Mode: audit (all threads)

1. Fetch all threads from the current month's section
2. Score each: Strong / Needs work / Pitch missing
3. Present a summary with recommendations on which to fix first

### Common Anti-Patterns

- **The Feature List** — features without arguing why they matter
- **The Empty Thread** — no notes, just a title
- **The Kitchen Sink** — everything buried together
- **The Assumed Conclusion** — jumps to "how" without "why"
- **The Vague Problem** — too abstract to act on
- **Opinion Disguised as Fact** — judgment in the What instead of So What
