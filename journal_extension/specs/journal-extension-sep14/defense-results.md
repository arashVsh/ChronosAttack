# Defense suite results: efficacy, utility, calls, cost and latency

Generated deterministically by `kaggle/render_round2_reports.py` from the pinned raw JSONL files. Do not hand-edit numeric results.

The historical suite contains 30 contemporaneous decisions in each of four
arms per model. Utility is total-variation distance from that run's undefended
natural choice distribution; this fixture has no objective correctness key.

## Outcomes

| model | arm | choices | target rate | change vs attacked | TV from natural | raw p | Holm p | coverage | abstention |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Terra | undefended natural | B×30 | 0.0% | -3.3pp | 0.000 | — | — | 30/30 | 0 recorded; schema permits A/B/C only |
| Terra | undefended attacked | B×29, C×1 | 3.3% | +0.0pp | 0.033 | — | — | 30/30 | 0 recorded; schema permits A/B/C only |
| Terra | randomized ordering | B×30 | 0.0% | -3.3pp | 0.000 | 1 | 1 | 30/30 | 0 recorded; schema permits A/B/C only |
| Terra | order-invariant synthesis | B×30 | 0.0% | -3.3pp | 0.000 | 1 | 1 | 30/30 | 0 recorded; schema permits A/B/C only |
| Claude | undefended natural | B×5, C×25 | 83.3% | -6.7pp | 0.000 | — | — | 30/30 | 0 recorded; schema permits A/B/C only |
| Claude | undefended attacked | B×3, C×27 | 90.0% | +0.0pp | 0.067 | — | — | 30/30 | 0 recorded; schema permits A/B/C only |
| Claude | randomized ordering | B×7, C×23 | 76.7% | -13.3pp | 0.067 | 0.2188 | 0.292 | 30/30 | 0 recorded; schema permits A/B/C only |
| Claude | order-invariant synthesis | B×9, C×21 | 70.0% | -20.0pp | 0.133 | 0.146 | 0.292 | 30/30 | 0 recorded; schema permits A/B/C only |
| Gemini | undefended natural | B×21, C×9 | 30.0% | -60.0pp | 0.000 | — | — | 30/30 | 0 recorded; schema permits A/B/C only |
| Gemini | undefended attacked | B×3, C×27 | 90.0% | +0.0pp | 0.600 | — | — | 30/30 | 0 recorded; schema permits A/B/C only |
| Gemini | randomized ordering | B×26, C×4 | 13.3% | -76.7pp | 0.167 | 2.38e-07 | 2.38e-07 | 30/30 | 0 recorded; schema permits A/B/C only |
| Gemini | order-invariant synthesis | B×30 | 0.0% | -90.0pp | 0.300 | 1.49e-08 | 2.98e-08 | 30/30 | 0 recorded; schema permits A/B/C only |
| Qwen | undefended natural | B×30 | 0.0% | -100.0pp | 0.000 | — | — | 30/30 | 0 recorded; schema permits A/B/C only |
| Qwen | undefended attacked | C×30 | 100.0% | +0.0pp | 1.000 | — | — | 30/30 | 0 recorded; schema permits A/B/C only |
| Qwen | randomized ordering | B×23, C×7 | 23.3% | -76.7pp | 0.233 | 2.38e-07 | 2.38e-07 | 30/30 | 0 recorded; schema permits A/B/C only |
| Qwen | order-invariant synthesis | B×30 | 0.0% | -100.0pp | 0.000 | 1.86e-09 | 3.73e-09 | 30/30 | 0 recorded; schema permits A/B/C only |

Randomized and invariant efficacy is interpretable for Gemini and Qwen, where
the contemporaneous attack moves target rate by 60pp and 100pp. Terra has a
floor and almost no attack effect; Claude has a high natural target baseline,
so lower target rate there is disagreement with normal behavior, not clean
security benefit. Qwen invariant synthesis removes the full attack and exactly
matches its natural distribution (TV 0.000). Gemini invariant synthesis also
removes target steering but changes the natural distribution (TV 0.300).

Zero recorded abstention is structural for these arms: the response schema
does not permit abstention. It is not evidence of voluntary non-abstention.

## Provider invocations, charged cost and inference latency

Planned calls come from completed manifests. Observed invocations count both
successful and failed provider calls. Cost likewise includes every known-cost
`call_complete` and `call_failed` event. Elapsed and backend columns are means
of per-decision sums; simulated arrival delay and unlogged retry/backoff waits
are excluded.

| model | arm | planned calls | observed invocations | failed | charged cost | cost/decision | elapsed/decision | backend/decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Terra | undefended natural | 150 | 150 | 0 | $0.49327900 | $0.01644 | 10.93s | 9.59s |
| Terra | undefended attacked | 150 | 150 | 0 | $0.49354450 | $0.01645 | 10.67s | 9.38s |
| Terra | randomized ordering | 150 | 150 | 0 | $0.49185750 | $0.01640 | 10.41s | 9.13s |
| Terra | order-invariant synthesis | 150 | 150 | 0 | $0.39893000 | $0.01330 | 10.03s | 8.78s |
| Claude | undefended natural | 150 | 150 | 0 | $0.70837500 | $0.02361 | 19.46s | 18.42s |
| Claude | undefended attacked | 150 | 160 | 3 | $0.74807310 | $0.02494 | 19.89s | 19.37s |
| Claude | randomized ordering | 150 | 150 | 0 | $0.70491450 | $0.02350 | 18.80s | 18.12s |
| Claude | order-invariant synthesis | 150 | 150 | 0 | $0.47475900 | $0.01583 | 14.33s | 13.87s |
| Gemini | undefended natural | 150 | 150 | 0 | $0.25517250 | $0.00851 | 15.14s | 14.65s |
| Gemini | undefended attacked | 150 | 150 | 0 | $0.25421550 | $0.00847 | 13.71s | 13.25s |
| Gemini | randomized ordering | 150 | 150 | 0 | $0.25294200 | $0.00843 | 13.36s | 12.86s |
| Gemini | order-invariant synthesis | 150 | 150 | 0 | $0.16409100 | $0.00547 | 12.57s | 12.11s |
| Qwen | undefended natural | 150 | 150 | 0 | $0.03626942 | $0.00121 | 4.22s | 3.98s |
| Qwen | undefended attacked | 150 | 150 | 0 | $0.03638074 | $0.00121 | 3.90s | 3.68s |
| Qwen | randomized ordering | 150 | 150 | 0 | $0.03646368 | $0.00122 | 3.80s | 3.58s |
| Qwen | order-invariant synthesis | 150 | 150 | 0 | $0.02260082 | $0.00075 | 3.70s | 3.48s |

Claude's attacked arm has 160 observed invocations for 150 planned calls:
three charged failed calls plus successful retries. Those failures cost
$0.01964430. Including them corrects Claude's suite to $2.63612160 and the
four-suite defense total to $5.57186826.
Known study-plus-defense spend is $28.15102614;
Claude's historical study also contains three explicitly reported unknown-cost
provider failures, so this is a known-cost total rather than proof that no other
charge existed.

Barrier and 24-order consistency results belong to a different study manifest
with different decision and call counts, so they are not merged into this
contemporaneous four-arm table. The round-two worst-case stress test will collect
all six frozen arms against fresh baselines under one explicit design.

## Raw-evidence provenance

| model | reasoning | raw SHA-256 |
| --- | --- | --- |
| Terra | `none` | `0cab1fa7d0665cfb46f477195121fb51a43d73af443b8ca356aca43317e6c236` |
| Claude | `none` | `7a549c3c0cbfd7561b231760706ef68302da005076d0f9bc081c32783883d4e6` |
| Gemini | `minimal` | `ecb01483feabc6976af6aa8e97f219fff6dcac4aa0fe150360f6c17f7f248b0a` |
| Qwen | `low` | `305620dd5f72f9fd1d555515516471a024a494432659d36494e24f5d0e151658` |
