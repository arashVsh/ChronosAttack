# Experiment A availability amendment, 2026-09-20

Status: **frozen before any Experiment A model call**. This amendment is
triggered solely by endpoint availability, not by an Experiment A outcome. It
supplements the previously frozen water-supply fixture and analysis contract;
it does not alter any option, payload, target, order, prompt, repetition,
endpoint, exclusion, or completed historical record.

## 1. Trigger and non-discretionary disposition

The primary round-two policy requires the lowest supported non-off reasoning
setting at each endpoint. Claude's original `minimal` compatibility request and
the single replacement authorized by the separately frozen retry amendment both
stopped on their first request with the same generic HTTP 500. Neither request
returned a completion or issued a compatibility receipt. Settled, hash-linked
Kaggle quota attestations show zero incremental charge. The bounded retry rule
therefore classifies the Claude matched non-off cell as operationally
unavailable and forbids another `minimal` request, a `low` request, or a receipt.

This availability decision was sealed before any water-supply call. It cannot
be revised after inspecting Experiment A choices.

## 2. Frozen roster and analysis roles

The approved four-endpoint roster remains fixed. Settings and roles are:

| endpoint | setting | Experiment A role |
| --- | --- | --- |
| `openai/gpt-5.6-terra` | `low` | matched non-off primary |
| `google/gemini-3.6-flash` | `minimal` | matched non-off primary |
| `qwen/qwen3-235b-a22b-instruct-2507` | `low` | matched non-off primary |
| `anthropic/claude-sonnet-4-6@default` | matched non-off unavailable | unavailable primary cell |
| `anthropic/claude-sonnet-4-6@default` | `none` | separately labelled reasoning-off sensitivity |

The three available matched non-off endpoints receive the unchanged frozen
690-trial / 2,310-planned-call water-supply study. If and only if its excluded
pilot passes, Claude `none` receives the same frozen 690-trial /
2,310-planned-call study as a sensitivity cell. It never fills, substitutes
for, or is pooled with the unavailable Claude matched non-off primary cell.

Thus the matched non-off primary collection has 2,070 trials and 6,930 planned
calls if complete. The predeclared, pilot-contingent Claude reasoning-off
sensitivity adds 690 trials and 2,310 planned calls. If every executable cell
completes, the physical collection still contains 2,760 trials and 9,240
planned calls, while its inferential roles remain distinct.

## 3. Primary hypotheses and multiplicity

The original eight-hypothesis family remains the confirmatory family: stateful
and stateless attack-minus-natural target-C effects for each of four endpoints.
Claude's two matched non-off hypotheses are non-evaluable because the endpoint
setting is unavailable; they are reported as unavailable, never as null effects
or observed p-values.

For family-wise error control, compute the frozen Holm procedure on the six
observed matched non-off p-values plus two structural values of one assigned
only for multiplicity accounting. These structural values are not outcome
imputation, are never presented as Claude p-values, and cannot make rejection
easier than the originally planned eight-test family. Report both raw and
eight-family Holm-adjusted p-values for the six evaluable hypotheses.

Claude `none` effects and exact tests are sensitivity-only. They are reported
with confidence intervals and raw p-values, outside the confirmatory family,
with no claim of matched cross-endpoint comparability. No pooled primary model
is introduced.

## 4. Compatibility pilots

The water-supply fixture is already immutable. Before a full cell, run one
excluded compatibility pilot at each executable endpoint/setting. Each pilot is
exactly two attempt-1 stateful jobs—natural repetition 1 and attack repetition
1—for ten planned calls. The real frozen prompts, schemas, token caps,
temperature, reasoning setting, evidence format, identity and strict audit are
used. Choices cannot affect authorization.

A pilot passes only if both jobs complete, all ten calls are accounted, cost is
known, identity and prompts match, and the strict water-supply audit passes.
Any truncation, provider error, unknown cost, malformed output, identity drift,
or audit failure stops that setting. No setting fallback, outcome-conditioned
retry, or silent token-cap change is allowed. A stopped Claude `none` pilot
makes only the sensitivity cell unavailable; it does not affect the three
matched non-off primary cells.

The four pilots are always excluded from confirmation. Their maximum allocation
is $0.25 per endpoint and $1.00 in aggregate. With the sealed prior daily spend
of $8.555856, launching all four on 20 September is authorized only while the
maximum daily exposure remains no more than $9.555856. Unknown cost stops the
sequence immediately. Full-study shard ceilings are fixed only after successful
pilot telemetry and must independently preserve the $10 daily cap.

## 5. Collection, failure, and reporting rules

- The frozen `water4` protocol, target C, natural and attack orders, seed,
  690-job topology, endpoints, exclusions, and fixed attack selection do not
  change.
- Use versioned, role-tagged study IDs and output roots so primary, sensitivity,
  and pilot evidence cannot collide.
- Use deterministic, outcome-independent shards with cumulative, byte-preserved
  evidence ledgers. Completed jobs are never replayed.
- Report every expected cell as complete, partial, failed, or unavailable.
  Scientific outcomes never determine continuation.
- Costs include charged failures. Unknown cost is not zero.
- Do not run Experiment B until Experiment A's executable cells are sealed and
  analyzed under this amendment. Experiment C remains after B.

## 6. Acceptance gate

Before the first Experiment A call, a self-hashed machine-readable manifest and
verifier must pin this amendment, the original fixture manifest, the Claude
terminal-result seal, the exact roles/settings, pilot topology, totals,
multiplicity treatment, budgets, and `collection_status=not_started`. Generated
task sources must then be byte-pinned and audited before upload.
