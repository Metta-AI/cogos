# Diagnosis Guide

How to classify feedback and determine what needs to change.

## Error Types

### 1. Calibration Error
**Pattern:** Candidates match criteria but score too high or too low.
**Evidence:** Feedback says "this person is good but scored low" or "scored high but doesn't seem right."
**Fix:** Adjust weights in `rubric.json`. Can auto-apply.
**Threshold:** 2 instances of same scoring mismatch.

### 2. Criteria Gap
**Pattern:** Good candidates rejected because a dimension is missing, or bad candidates accepted because a dimension is wrong.
**Evidence:** Feedback identifies a trait we're not measuring, or a trait we're measuring wrong.
**Fix:** Patch `criteria.md`. Requires Discord approval.
**Threshold:** 3 similar rejections or acceptances that point to the same missing/wrong criterion.

### 3. Strategy Error
**Pattern:** Not finding the right people, or finding people in the wrong places.
**Evidence:** Consistent feedback that sourced candidates are "not our type" despite matching criteria.
**Fix:** Rewrite `strategy.md` or individual `sourcer/*.md` files. Requires Discord approval.
**Threshold:** 5 rejections from the same source without a single acceptance.

### 4. Process Error
**Pattern:** Fundamental approach is broken — wrong questions, wrong presentation, wrong flow.
**Evidence:** Feedback about how candidates are presented or evaluated, not who they are.
**Fix:** Modify process prompts. Requires Discord approval.
**Threshold:** Direct feedback about process issues, or 3 process-related complaints.

## Escalation Rules
- Always try the cheapest fix first (1 → 2 → 3 → 4)
- Never skip levels — a calibration adjustment might fix what looks like a criteria gap
- Auto-apply only level 1 changes; all others require approval
- Log every change attempt to `evolution.md`, even rejected ones

## What Can Be Auto-Applied
- `rubric.json` weight adjustments (level 1)
- Nothing else — everything else needs human approval via Discord
