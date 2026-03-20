# Cogtainer Status Canonicalization

## Problem

`src/cogtainer/status.py` still contains compatibility logic for mixed-quality
rows in `cogent-status`.

Today we still have helpers that:

- infer stack names from cogent names
- infer cogent names from stack names
- coalesce multiple status rows that refer to the same cogent

That is a smell. The status model should not need merge heuristics or name
parsing once identity is explicit.

## Desired End State

There is exactly one status row per cogent, keyed by canonical
`cogent_name`.

The watcher should:

- discover the canonical cogent identity from a concrete stack tag
- update the existing status row for that cogent
- never create a second stack-name-derived identity

The CLI should:

- read the canonical row directly
- stop coalescing duplicate rows at display time

## Concrete Plan

1. Backfill `cogent_name` tags onto existing cogtainer stacks.
2. Make the watcher require or prefer the `cogent_name` stack tag.
3. Change watcher writes to update the canonical `cogent_name` row instead of
   emitting a separate runtime identity.
4. Run a one-time cleanup for old `*-cogtainer` / duplicate status rows in
   `cogent-status`.
5. Delete the normalization layer in `src/cogtainer/status.py`.
6. Move any remaining stack-naming helper into a small naming module if still
   needed.

## What Should Go Away

If the plan above is completed, these should be removable from
`src/cogtainer/status.py`:

- `safe_name_from_stack_name`
- `status_stack_name`
- `coalesce_status_items`
- `record_type`

`expected_stack_name` may still be useful as a naming helper, but it should
not be part of status reconciliation logic.

## Principle

Use declared metadata, not inferred identity.

- `cogent_name` tag on the stack
- one Dynamo row per cogent
- direct reads and updates by canonical identity
