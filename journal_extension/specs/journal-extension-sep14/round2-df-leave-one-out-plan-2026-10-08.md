# Round 2 D and F: leave one observation out, three versus four observations (2026-10-08)

Status: frozen before any call. Arash (email of 2026-10-08) asked to complete the
experiments; Masih left the D/F design to the agent.

## Questions

- D (Arash section 5, "remove one observation"): does one observation drive most of
  the order sensitivity?
- F (Arash section 5, "three vs. four observations"): does the effect change when the
  scheduling space grows from 6 to 24 orders?

One design answers both.

## Design

- Scenario: the tree scenario of round one, B, C and E, with one tool removed at a
  time. That gives four three-observation variants: no equity, no heat, no survival,
  no cost. Payload bytes of the remaining three tools are unchanged.
- Harness: the original three-tool engine `completion_protocol.py`, unmodified
  (step prompt `TOOL OBSERVATION k/3`, "Three independent tools are running",
  final call at step 4). A private, unpatched instance is loaded; no frozen file is
  edited.
- Wording: the system prompt drops the removed criterion from its two criterion
  sentences and nothing else; the final prompt says "three" instead of "four".
  Otherwise the model would be told to weigh a criterion it never receives evidence
  for. Exact texts are in `kaggle/experiment_df_protocol.py`.
- Orders: all 6 orders of the three remaining tools, stateful, 10 repetitions each
  (complete 6-order panels, the counterpart of the 24-order panels with 10
  repetitions each). The variant's natural order is the four-tool natural order
  without the removed tool; its attack order is the four-tool attack order without it.
  With equity removed the two coincide, so the fixed attack does not exist there.
- Trials: 4 variants x 6 orders x 10 = 240 trials (960 calls) per model, 960 trials
  in total. Target: C, as in the four-tool scenario.
- Models and settings: Terra-low, Gemini-minimal, Qwen-low, Claude with reasoning off;
  temperature 1, 256-token cap, 30 s timeout, as in E.
- Four-observation reference: the existing complete 24-order stateful panels (10
  repetitions) of the same four cells. They were collected in September; the time gap
  is disclosed.

## Outcomes (exploratory, descriptive, no hypothesis tests beyond the panel null)

Per model and variant:
1. Target rate per order (6 orders), natural and attack orders, worst and best order.
2. Order information: plug-in mutual information between order and final choice,
   with the panel-preserving permutation null of `analyze_four_observation.py`
   (999 shuffles, seed 20260909), and the null mean so that bias is visible.
3. Choice distribution and entropy.

F compares these with the four-tool panels (24 orders). D compares the four
variants with each other and with the four-tool panel.

## Execution

- Same machinery as E: hash-frozen manifest, 30 deterministic shards per model (8
  trials, 32 calls each), $0.60 hard ceiling per shard, graceful stop and full raw
  ledger, transport wait for RateLimitError and APITimeoutError (7,200 s per call),
  a stopped or failed shard reruns from scratch as r1..r3 and every attempt is kept
  and costed. Lanes run per model in parallel; the Kaggle meter is read at the start
  and end of each lane period.
- Budget: about $8 at E's per-call prices; stop and report before the monthly meter
  passes $60 or a day passes $9.
