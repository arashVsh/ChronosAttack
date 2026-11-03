# Round 2: reinstating Claude's matched non-off cell at `low` (2026-09-27)

Written before the `low` preflight. Masih directed it ("go ahead, do it").

## Basis

`round2-claude-reasoning-recheck-2026-09-27.md` records the evidence. On Kaggle,
Claude `minimal` failed with HTTP 500 on every request: three preflights (09-20
twice, 09-27) and five diagnostic calls, at every token cap and answer format.
In the same runs `low` and `none` passed. So `minimal` is treated as
**unsupported**. Kaggle signals this with a generic 500, not the 400 the frozen
gate expects.

## Rule

1. `kaggle/claude_low_chain_v1.py` pins the three raw `minimal` preflight
   ledgers and terminals and the two diagnostic result files by SHA-256. It
   re-checks them and issues a `minimal_unsupported` disposition with the basis
   `deterministic_http_500`. It stands in the frozen chain exactly where
   the 400-based receipt would, and changes nothing else.
2. The unchanged frozen `low` preflight then runs once. Its strict gate decides
   pass or stop, with no retries.
3. If it passes, Claude-low is the matched non-off Claude cell. It runs in Arash's
   order: round-one study and defenses, then A, B and C. Each experiment gets its
   own short amendment adding the cell, with the same jobs, prompts, seeds, arms
   and analysis as the other matched models. Claude-none stays a sensitivity cell.
4. Runs are serial under the existing quota and replay gates. They are spread
   across days as the Kaggle credit allows.

## Outcome, 2026-09-27 05:00 UTC: paused

- The `low` preflight passed (10/10, $0.0438696, receipt `19b14838...`).
- Study shard s00 ran as r0–r9 (new task per resume, completed-jobs seed). It
  reached 43/69 jobs for about $1.15 known cost. Job `permutation_stateful|5|9`
  failed at step 4 on all three in-run attempts with `LengthFinishReasonError`
  (256 output tokens, thinking included) in r6, r7 and r8.
- The runner's completed-jobs projection reset the attempt counter. That
  bypassed the frozen three-attempt limit, so r7 onward retried a job the
  frozen rules had already stopped. Those runs are pinned and costed. They must
  not count as valid attempts, and the shard is **stopped** by the frozen rule.
- Conclusion: under the frozen 256-token cap, Claude `low` cannot complete
  every trial. Raising the cap for this cell is a protocol change. It is put to
  Arash, and nothing more runs until he answers.

## Decision, 2026-09-27 09:00 (Arash's reply)

Arash: "I think Claude with reasoning off is enough." The Claude-low branch is
closed. No more Claude-low runs will happen. The s00 runs and the preflight stay
pinned as a record. Claude-none remains the Claude cell in every experiment.
