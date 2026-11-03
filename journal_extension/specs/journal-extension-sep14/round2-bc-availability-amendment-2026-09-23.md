# Experiments B and C availability amendment, 2026-09-23

Status: **frozen before any Experiment B or C model call**. This disposition
changes only which already-approved reasoning settings are executable and how
their evidence is labelled. It does not revise the frozen tree fixture, label
rotations, pair counts, defense arms, selection rule, endpoints, or exclusions
in the [round-two amendment](round2-amendment-2026-09-20.md). Experiment A
outcomes were available when this note was written; no B or C outcomes were.
Neither B nor C continuation, analysis, or stopping is conditioned on A choices.

## Availability and inferential roles

The [pre-outcome availability disposition](round2-experiment-a-availability-amendment-2026-09-20.md)
sealed Claude's matched non-off setting as operationally unavailable after the
bounded retry. It forbids further `minimal` and `low` attempts. This is an
endpoint restriction, not a water-supply-specific scientific result, and it
continues to apply to B and C. The approved four-endpoint roster remains fixed:

| endpoint | setting | B and C role |
| --- | --- | --- |
| `openai/gpt-5.6-terra` | `low` | matched non-off primary |
| `google/gemini-3.6-flash` | `minimal` | matched non-off primary |
| `qwen/qwen3-235b-a22b-instruct-2507` | `low` | matched non-off primary |
| `anthropic/claude-sonnet-4-6@default` | matched non-off | unavailable primary cell |
| `anthropic/claude-sonnet-4-6@default` | `none` | reasoning-off sensitivity only |

Claude `none` never fills or substitutes for Claude's matched non-off cell and
is not pooled with the three primary settings. If a cell cannot be completed,
report it as partial, failed, or unavailable with its raw evidence and cost.
No new reasoning-setting fallback is permitted.

## Experiment B execution gate

Preserve three cyclic maps, semantic target C, unchanged numeric fixture,
tool identities and orders, and 30 fresh stateful natural/attack pairs per
map and executable setting. Each completed setting contributes 180 study
trials and 900 planned calls. The three matched primary settings total 540
trials/2,700 planned calls; the separately labelled Claude `none` sensitivity
adds 180 trials/900 planned calls. No B model call starts until Experiment A's
four executable cells are strictly sealed and its frozen analysis completed.

After the B source, fixture, and manifest are pinned, use one excluded
compatibility pilot at each executable setting: exactly the rotation-1
stateful natural/attack repetition-1 pair, two jobs and ten planned calls,
with separate pilot IDs/output. Passing depends on complete identity,
remapping, prompt and cost evidence, not on which option is chosen. A failed
pilot stops only that setting. Pilot outcomes are never included in the 30
confirmatory-study repetitions. The B analysis remains
exploratory-descriptive; report semantic and literal choice separately.

## Experiment C execution gate

Preserve all six arms and 30 repetitions per arm. From each executable
setting's own *complete tree-fixture stateful 24-order panel* (ten repetitions
per order), select the order with highest target-choice rate and break ties by
the lowest frozen condition index. Seal model, setting, role, raw source-log
SHA256 and selected order before fresh C outcomes. Claude `none`, if run,
selects from its own reasoning-off tree panel and remains sensitivity-only;
there is no selected order for unavailable Claude matched non-off. B must be
completed or explicitly reported partial before C outcome calls start.

The three matched primary C cells require 4,110 planned calls (Terra 1,350;
Gemini 1,380; Qwen 1,380). Claude `none` sensitivity adds 1,350. Preserve
the 24-order consistency vote including `ABSTAIN`, the canonical barrier,
seeded randomization, and invariant synthesis with the exact same four
isolated summaries reused for forward and reverse synthesis at Gemini and
Qwen. C remains a post hoc stress test, not new confirmatory evidence.

## Evidence, quota, and stopping

Before any B or C upload, pin a versioned self-hashed executable manifest,
source hash, expected job IDs, roles, settings, costs and strict auditor.
Use deterministic outcome-independent shards and identity-aware resume;
completed jobs are never replayed. Apply the existing maximum of $10 Kaggle
free credit per day with a fresh official quota attestation and conservative
per-shard ceiling. Unknown cost, malformed evidence, source/identity drift,
failed strict audit, or insufficient remaining authorization stops further
calls for the affected phase. A daily reset permits later continuation but
does not revise the scientific contract. All charged attempts count in cost.
