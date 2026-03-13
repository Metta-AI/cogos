# Fibonacci Demo App

`fibonacci` is the smallest possible session-reentrant demo.

It exists to show one thing clearly: the process can wake, answer once, stop,
and then continue from the prior run's conversation state on the next wake.

## Shape

- process: `fibonacci`
- wake channel: `fibonacci:poke`
- session mode: `process`

There is intentionally no keyed session behavior here. This demo owns one
rolling sequence per process so the reentrancy behavior is obvious.

## Flow

1. Send any message to `fibonacci:poke`
2. The process wakes
3. It resumes the prior conversation, computes the next Fibonacci step from the
   latest prior step in that transcript, and replies with a single line
   describing the next step
4. It stops
5. The next `fibonacci:poke` repeats from the resumed session transcript

## Example

```bash
cogent local cogos channel send fibonacci:poke --payload '{}'
cogent local cogos channel send fibonacci:poke --payload '{}'
cogent local cogos channel send fibonacci:poke --payload '{}'
```

Then inspect the latest run logs in the dashboard, or via:

```bash
cogent local cogos run list
```

Expected first assistant replies:

- `index=0 value=0`
- `index=1 value=1`
- `index=2 value=1`

## Why this app exists

This is the demo for simple process-scoped session reentrancy before
introducing keyed session selection. If this app is hard to reason about, the
bigger keyed examples will also be hard to reason about.
