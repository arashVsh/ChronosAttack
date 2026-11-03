# Round-two attempt-extension amendment, 2026-09-20

Status: **frozen before the repair call**.

Masih approved continuation at 18:04 Asia/Tehran after the handoff identified
this exact amendment as the decision required to resume. This amendment is
narrowly scoped to the immutable Terra shard-00 ledger below. It supplements
`round2-amendment-2026-09-20.md`; it does not rewrite completed evidence or
authorize any other stopped phase.

## 1. Triggering evidence

- Model: `openai/gpt-5.6-terra`.
- Reasoning: `low`.
- Study: `chronos_round2_terra_reasoning_study_low_v1`.
- Shard: 0 of 10, 69 jobs / 217 originally planned calls.
- Parent raw evidence SHA-256:
  `b22e7bb7a5cf1e20cb5e106d81c4c8d1c4c01aefbe5b1c9d0a1f3992fa490a7b`.
- Parent accounting: 35 completed jobs, 119 provider invocations, four charged
  failures, no unknown-cost calls, $0.338884 known cost.
- Terminal job:
  `chronos_round2_terra_reasoning_study_low_v1|study|openai/gpt-5.6-terra|tree4|stateful|natural|7`.
- That job has attempts 1, 2 and 3, each ending in a fully costed
  `LengthFinishReasonError` at step 4 and exactly 256 output tokens.
- The same parent ledger contains one earlier step-4 256-token truncation on
  `budget|0|6`; the unchanged attempt 2 completed successfully.

The amendment decision uses only failure topology, accounting and the frozen
runner's already-declared treatment of length truncation as a retryable
technical failure. No completed choice or treatment-effect estimate determined
this repair.

## 2. Sole method change

For the exact terminal job above, increase the maximum total attempts from 3 to
6. Resume at attempt 4. Attempts 4, 5 and 6 use the identical model, reasoning,
temperature, prompt, schema, 256-token cap, timeout and SDK zero-retry setting.

All other jobs retain the original three-attempt maximum. A completed job is
never replayed. The terminal job is never skipped or relabelled complete.

An additional attempt is permitted only when the immediately preceding attempt
ended in a known-cost `LengthFinishReasonError`. No valid result, provider
refusal, timeout, schema failure, unknown-cost call or scientific outcome is
retryable under this amendment.

## 3. Evidence and identity

- The parent raw file must be copied byte-for-byte as the exact prefix of the
  descendant ledger and must end in a newline before append.
- The parent hash, model, reasoning, study ID, identity, manifest, job and
  attempts 1–3 are revalidated locally and again inside the hosted task before
  any call.
- The four historical frozen modules remain byte-identical. A versioned repair
  runner and versioned auditor implement this amendment without editing them.
- The strict auditor accepts attempts 4–6 only for the exact terminal job and
  only with the failure chain above. Attempts above 3 on any other job fail.
- Every failed call remains in cost, latency and failure accounting.

## 4. Execution and stopping

- Repair task: `chronos-r2-terra-study-low-s00-repair-v1`.
- The incremental allocation is at most $0.95; the effective engine ceiling is
  the exact $0.338884 parent spend plus that increment.
- If the terminal job completes by attempt 6, the same deterministic shard may
  continue its unstarted jobs under their original three-attempt rule.
- If attempt 6 does not complete, cost becomes unknown, identity/prefix/audit
  validation fails, authorization is exhausted, or any non-length error
  reaches the evidence layer, stop normally and preserve the full ledger. Do
  not advance to another job.
- Shards 01–09 remain unlaunched until the repaired shard passes its amended
  strict audit.

## 5. Acceptance before push

The task may be pushed only after local tests prove that the versioned repair:

1. accepts the exact parent and returns next attempt 4;
2. rejects a changed byte, identity, job, cost, cap, error type or attempt gap;
3. rejects attempt 7 and attempts 4–6 on any other job;
4. preserves the complete parent byte prefix and counts its $0.338884 spend;
5. skips all 35 completed jobs without replay;
6. stops at attempt 6 if the terminal job remains incomplete;
7. revalidates the Terra receipt chain and exact shard manifest; and
8. regenerates the hosted source byte-for-byte from pinned inputs.

Nothing in this amendment authorizes retrying Claude's generic HTTP 500,
changing a token cap, altering Experiment A, sending email, publishing, or
pushing repository changes.
