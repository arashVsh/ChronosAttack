# Round 2 B: Qwen-low study shard 25 replacement note (2026-09-26)

Written before the replacement run, after the failure and before any of its data.

## What happened

`chronos-r2-tree4-rotation-study-qwen-low-s25-v1` ran 17:03:37–17:04:22 UTC.
Jobs 1–2 of 6 completed. At job 3 (`tree4_rot0|stateful|attack|18`, step 2) the
provider returned a JSON answer cut off mid-string. The SDK raised
`ResponseParsingError`. That call reported no usage, so its cost is unknown to the
raw ledger. The run stopped on the error, as the frozen runtime requires.

- Raw known cost: $0.00254188 over 11 completed calls, plus 1 failed call of unknown cost.
- Signed-in monthly quota change across the run: $0.00293810. The meter
  therefore attributes $0.00039622 to the unpriced call.

## Why the written resume rule cannot apply

Rule 4 of the transport-wait amendment says an incomplete shard is resumed with
the frozen B `--resume-from` path. The frozen resume validator
(`round2_hosted.validate_resume_ledger`) rejects every parent ledger that holds a
call of unknown cost. So this shard cannot be resumed without editing frozen code,
which we do not do.

## Decision

1. The failed run is kept, pinned and disclosed. It is not analysed. Its two
   completed trials are not used.
2. Shard 25 is run once more, from scratch, as
   `chronos-r2-tree4-rotation-study-qwen-low-s25-r1-v1` (folder
   `round2_tree4_rotation_study_qwen_low_s25_r1_v1`). Its source is the same
   deterministic shard source, with only the task and folder names changed. It uses the same
   frozen ceiling, fresh quota readings before and after, and the same frozen raw
   replay and quota-equals-cost check.
3. The replacement's six trials stand in the analysis for shard 25, whatever they
   show. If the replacement also fails to complete, no further attempt is made
   and the Qwen-low cell is reported as partial.
4. This applies to this one shard only. The B v2 collection pins this note, lists
   the replaced run with its cost and its meter-attributed unknown cost, and
   reports it beside the cell totals.

Why this is fair: the failure was a transport-level truncation. It happened before
the trial produced a decision. The replacement is decided before its outcome is
known, and it runs the same pre-registered jobs.
