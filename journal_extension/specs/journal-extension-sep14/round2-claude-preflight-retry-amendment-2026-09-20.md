# Round-two Claude preflight-retry amendment, 2026-09-20

Status: **frozen before the replacement preflight**.

Masih explicitly authorized Kaggle uploads and runs and directed the work to
continue through operational failures. This amendment resolves one narrow
scientific ambiguity left by the original compatibility rule. It supplements
`round2-amendment-2026-09-20.md`; it does not change the primary roster,
reasoning policy, prompts, outcome definitions or any completed evidence.

## 1. Triggering evidence

- Model: `anthropic/claude-sonnet-4-6@default`.
- Reasoning setting under test: `minimal`, the first setting in the frozen
  `minimal`-then-`low` compatibility sequence.
- Original task: `chronos-r2-claude-preflight-minimal-v1`, version 1, run
  2647262.
- Original study ID:
  `chronos_round2_claude_reasoning_preflight_minimal_v1`.
- Raw evidence SHA-256:
  `8cb0b2cecd7cb0ba2b22b3f84fdd4dca6e11a3199b975405362431c48b10da1d`.
- Terminal SHA-256:
  `84fd465308adb45169b01d098a775fbae661ee2f4a1802d47a0554ff410d0ae9`.
- The exact event topology is `job_started`, one step-1 `call_failed`, then
  `job_error`. The failed call has no completion, no tokens and no reported
  cost. Its error is `InternalServerError`, HTTP 500, with only the generic
  message “An internal server error occurred.”
- An authenticated quota attestation queried more than five minutes after the
  event reports the same $0.030434 daily usage as before the Claude request.
  The stopped request therefore added $0, but its error does not establish
  whether `minimal` is supported.
- No Claude compatibility receipt was issued. No scientific choice or outcome
  was observed.

## 2. Sole method change

Permit exactly one replacement of the complete two-job/ten-call `minimal`
compatibility preflight. It is a replacement for a zero-completion generic
transport failure, not a resume and not a replay chosen after observing an
answer.

The replacement uses:

- study ID
  `chronos_round2_claude_reasoning_preflight_minimal_retry_v1`;
- task `chronos-r2-claude-preflight-minimal-retry-v1`;
- output folder
  `round2_claude_reasoning_preflight_minimal_retry_v1`;
- the identical model, fixtures, two jobs, ten planned calls, prompts, schemas,
  temperature 1, `minimal` reasoning, 256-token cap and 30-second timeout;
- SDK `max_retries=0`, no transport wait/retry, and attempt 1 only; and
- a $0.25 hard incremental ceiling.

The original evidence remains immutable and is not embedded as a resume seed,
because preflight outcomes must never be merged or selectively skipped. The
new study identity makes the replacement ledger independently auditable while
the amendment and prelaunch manifest bind it to the original stopped run.

## 3. Outcome-independent decision rule

1. If all ten calls complete on attempt 1 and the strict preflight gate passes,
   issue a `minimal` passed receipt. Select `minimal`; do not run `low`.
2. If the first request returns an explicit 400/422 reasoning-parameter
   rejection naming `minimal` as unsupported, with no completion and resolved
   zero incremental cost, issue the existing `minimal_unsupported` receipt.
   Then run exactly one ordinary `low` preflight under the original sequence.
3. If any generic 5xx, rate limit, timeout, connection error, truncation,
   schema error, unknown-cost event or other outcome occurs, issue no receipt
   and classify Claude as operationally unavailable for the matched-setting
   matrix. Do not retry again.
4. A `low` preflight, if reached through rule 2, is governed by the same exact
   ten-call topology, $0.25 ceiling and no-retry rule. It either passes and
   selects `low`, or stops the Claude branch without another retry.

These rules were fixed without seeing a replacement response.

## 4. Budget and stopping

Exact known 20 September spend before this replacement is $8.555856. The
replacement ceiling makes the maximum $8.805856. If and only if rule 2
authorizes a `low` preflight, its additional $0.25 ceiling makes the combined
maximum $9.055856, below the $10 daily limit.

Stop normally and preserve evidence on every failure. Unknown cost is never
treated as zero without a settled, hash-linked Kaggle attestation. A successful
compatibility receipt authorizes later full-cell generation but does not waive
the separate full-cell budget and shard gates.

## 5. Acceptance before push

The replacement task may be pushed only after local checks prove that:

1. every triggering artifact and its settled quota attestation is hash-pinned;
2. the generic HTTP 500 cannot itself issue any receipt;
3. the replacement source is a byte-exact regeneration of the versioned
   builder with the identifiers and $0.25 ceiling above;
4. the generated manifest has exactly two jobs and ten planned calls;
5. the source has no resume seed, SDK retry or transport wait budget;
6. the source-hashed historical modules remain unchanged;
7. the original and replacement study identities differ; and
8. the two possible daily maxima remain below $10.

Nothing in this amendment authorizes changing the Claude endpoint, silently
advancing to `low`, retrying a second generic failure, editing frozen modules,
starting Experiment A, sending email, publishing or pushing repository state.
