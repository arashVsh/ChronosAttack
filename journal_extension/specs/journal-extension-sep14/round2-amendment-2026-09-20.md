# Round-two protocol amendment, 2026-09-20

Status: **frozen before any new model call**. This amendment records the
decisions in Arash's latest reply. It supplements, rather than rewrites,
`analysis-plan.md`; classifications attached to completed runs remain
historical facts.

## 1. Reporting hierarchy

- The primary paper matrix is Terra, Claude, Gemini and Qwen at each endpoint's
  lowest supported non-off reasoning setting.
- "Matched" means one reasoning-enabled policy across endpoints. It does not
  claim equal reasoning-token budgets or identical provider implementations.
- Existing Terra and Claude `reasoning="none"` runs keep their original
  confirmatory provenance. In the revised cross-model presentation they are a
  reasoning-off sensitivity analysis, never overwritten or relabelled as new
  data.
- Existing Gemini `minimal` and Qwen `low` cells remain the primary cells for
  those endpoints.
- The original fixed-order tests, exploratory held-out order selection, and
  post hoc worst-case defense stress test are separate analyses. None replaces
  or upgrades another.
- In the threat model, delay is the attacker's means of inducing an order. In
  this implementation the model sees delivered order only; simulated arrival
  times never enter its prompt. No timing harness or delay-magnitude experiment
  will be built in this round.

## 2. Roster and scope

| endpoint | primary reasoning setting | completed setting | action |
| --- | --- | --- | --- |
| `openai/gpt-5.6-terra` | lowest accepted non-off, resolved by preflight | `none` | new study and defense cells |
| `anthropic/claude-sonnet-4-6@default` | lowest accepted non-off, resolved by preflight | `none` | new study and defense cells |
| `google/gemini-3.6-flash` | `minimal` | `minimal` | retain |
| `qwen/qwen3-235b-a22b-instruct-2507` | `low` | `low` | retain |

Qwen remains the fourth main model. DeepSeek V4 Flash is optional,
supplementary, separately provider-labelled, and cannot delay the four-model
matrix. Leave-one-out, paraphrase and controlled 3-vs-4 observation experiments
are deferred until A, B and C are complete.

## 3. Analysis repairs before calls

All repaired outputs derive from immutable raw JSONL, not trusted intermediate
summaries.

### Four-model descriptive analyses

Regenerate inversion, tool-position and trajectory results rather than appending
a Qwen row. Qwen changes the interpretation of the first two analyses, so the
existing prose is not retained automatically.

### Held-out best-order analysis

- Input: ten complete `permutation_stateful` repetitions per model.
- Split seed: `20260920`, sampled once without inspecting split outcomes.
- Selection repetitions: `3, 4, 5, 7, 10`.
- Evaluation repetitions: `1, 2, 6, 8, 9`.
- Selection objective: highest target-choice rate over the selection half.
- Tie-break: lowest frozen permutation condition index.
- Evaluation: paired selected-order versus natural-order outcomes within the
  held-out half. Report effect and raw outcomes descriptively; with five pairs,
  even five gains and zero losses cannot produce a two-sided exact p below 0.05.
- Selection rows may never enter evaluation calculations.

### Model-by-order regression

- Outcome: target-C choice in stateful 24-order panels.
- Predictors: categorical model, categorical order and their interaction.
- Estimator: separation-resistant Firth logistic regression; no ordinary-MLE
  Wald inference.
- Report predicted cell probabilities and one global interaction assessment,
  not a catalogue of fragile coefficient p-values.
- The global assessment is a Firth penalized likelihood-ratio comparison of
  the full interaction and additive predictors, using the full-model Jeffreys
  penalty under both nested fits and an exploratory asymptotic chi-square
  reference with 69 degrees of freedom.
- Uncertainty resamples complete 24-order repetition panels within model using
  2,000 percentile-bootstrap draws and seed `20260920`. Repetition IDs are
  balanced-panel bookkeeping, not temporal or subject identities.
- Declare and test the numerical dependency on separated synthetic cells before
  using it on study data.

These numerical implementation details were fixed during the dated repair of
already observed historical data. They do not upgrade the regression from its
exploratory classification.

### Defense telemetry

- Utility is total-variation distance from the same run's undefended-natural
  choice distribution. The scenario has no objective correctness key.
- Coverage and recorded abstention are reported together. Existing
  randomized/invariant arms use a forced-choice A/B/C schema, so their value is
  labelled `0 recorded; abstention not permitted`, not interpreted as voluntary
  non-abstention.
- Planned calls per decision and observed provider invocations are separate.
  Observed invocations include charged failed calls and retries.
- Cost sums every `call_complete` and `call_failed` event with known cost;
  unknown cost remains unknown.
- Inference elapsed time sums recorded per-call `elapsed_seconds` used to obtain
  a completed decision and is summarized by the mean and median across
  decisions. Provider backend latency is treated the same way and reported
  separately with missingness. Simulated arrival delays are excluded. Run-level
  transient wait time is reported separately because it cannot be assigned
  reliably to a decision.
- Extra calls are relative to the contemporaneous undefended-attacked arm;
  absolute planned calls are always shown.

## 4. Reasoning-alignment collection

Historical frozen modules remain byte-identical. Generated tasks set a new
versioned study ID and output root so reasoning-on evidence cannot collide with
reasoning-off evidence.

For Terra and Claude, try `minimal` first and `low` only if the endpoint rejects
`minimal` as unsupported. This is a compatibility sequence, not an outcome
search. Record the accepted setting before the full cell.

The preflight uses the real stateful natural/attack path: ten calls, the final
256-token cap, schemas, temperature, retry policy, evidence logging and cost
telemetry. A result passes regardless of its choices. Any truncation, unknown
cost, identity mismatch, or invalid resume seed stops the phase. The token cap
is not silently raised; doing so requires a new amendment.

After successful preflight, collect per model:

- study: 690 trials / 2,310 planned calls;
- defense: 120 trials / 600 planned calls.

Total Terra plus Claude: 1,620 trials / 5,820 planned calls, excluding preflight
and retries. Old checkpoints cannot seed new settings.

## 5. Experiment A: second independent scenario

Use a genuinely different decision domain and tradeoff geometry. A water-supply
resilience investment is the working domain, not yet a frozen fixture. Before
any outcome-bearing call, a versioned self-hashed protocol must freeze its
options, four payloads, semantic target, natural order, fixed attack order,
endpoints, repetitions, exclusions, multiplicity family and analysis.

Once frozen, run the same 690-trial / 2,310-call study design on all four models:
2,760 trials / 9,240 planned calls. Compatibility pilots occur only after the
fixture is immutable and are excluded from confirmation. Null and partial
results remain reportable.

## 6. Experiment B: label rotation

Generate three cyclic mappings from one semantic tree fixture:

- rotation 0: semantic A/B/C -> label A/B/C;
- rotation 1: semantic A/B/C -> label B/C/A;
- rotation 2: semantic A/B/C -> label C/A/B.

The semantic target is the original option C. Tool identities, values, natural
order and attack order do not change after inverse label mapping. Collect fresh
stateful natural/attack pairs for all three mappings: 30 pairs per mapping and
model, or 720 trials / 3,600 planned calls across four models. Report semantic
choice and literal-letter choice separately. This is exploratory-descriptive.

## 7. Experiment C: worst-case defense stress test

After the matched tree matrix is final, select each model's strongest order
from all ten stateful permutation repetitions. Objective: target-choice rate;
tie-break: lowest frozen condition index. Freeze model, reasoning setting,
source-log SHA256 and selected order before fresh defense outcomes. This is a
post hoc stress test.

Default arms, 30 repetitions each:

1. fresh undefended natural stateful baseline;
2. fresh undefended selected-order stateful attack;
3. barrier synchronization;
4. full 24-order consistency vote;
5. seeded randomized ordering;
6. order-invariant synthesis.

Barrier canonical order is fixture natural order. Invariant canonical order is
alphabetical tool ID, matching the completed defense implementation; its
reversal is the exact reverse of that alphabetical order.

For Gemini and Qwen, each invariant repetition makes four isolated summary
calls once, then two synthesis calls over byte-identical summaries in forward
and reverse canonical order. Independent re-summarisation is forbidden because
it would confound order with summary sampling.

Under this arm set the planned total is 5,460 calls: 1,350 each for Terra and
Claude and 1,380 each for Gemini and Qwen. Defense efficacy compares with the
fresh selected-order arm; utility compares with the fresh natural arm.

## 8. Evidence, budget and stopping rules

- Raw attempts, failures, prompts, settings, timings and costs are immutable.
- Every task has a versioned study ID, explicit output root, expected manifest,
  strict auditor and identity-aware resume seed.
- Use small deterministic shards. A shard boundary never depends on outcomes.
- The existing authorization remains at most $10 free Kaggle credit per day.
  Per-cell ceilings come from successful preflight telemetry and remaining daily
  credit, not historical reasoning-off prices.
- Provider refusal may stop and resume a shard; scientific outcomes may not.
- Unknown cost, invalid identity, malformed evidence, exhausted authorization,
  or a failed strict audit stops further calls.
- Nothing is emailed, uploaded, published or pushed without Masih's explicit
  instruction.

## 9. Round acceptance

The round is agent-verified only when a fresh extraction regenerates every
revised table and figure, selection and evaluation inputs are disjoint, all
reported costs include charged failures, all expected cells are audited or
explicitly labelled partial, and a new dated package verifies without trusting
an intermediate analysis file. Masih's review is the final acceptance step.
