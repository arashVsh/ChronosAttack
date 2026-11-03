# Inversion-count ablation: distance is not a sufficient attack model

Generated deterministically by `kaggle/render_round2_reports.py` from the pinned raw JSONL files. Do not hand-edit numeric results.

The prespecified `budget` arm contains 15 trials at each inversion distance
from 0 through 6. These are descriptive target-C rates; the cross-distance
interpretation is exploratory.

## Target-choice rate by inversion distance

| model | inv0 | inv1 | inv2 | inv3 | inv4 | inv5 | inv6 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Terra | 0.0% | 0.0% | 0.0% | 0.0% | 20.0% | 0.0% | 6.7% |
| Claude | 86.7% | 93.3% | 66.7% | 0.0% | 66.7% | 80.0% | 93.3% |
| Gemini | 40.0% | 0.0% | 40.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| Qwen | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% | 100.0% | 100.0% |

Terra, Claude and Gemini are non-monotonic. Qwen is different: it is at
0% for distances 0–3 and 100% for distances 4–6. Qwen therefore rules
out the old claim that inversion distance carries almost no information
in every model. The defensible four-model conclusion is narrower:
distance is not a sufficient description of a schedule's effect.

## Equal-distance counterexample

The fixed attacked order and the lexicographically frozen budget order are
both distance 3 from natural order, but they are different permutations.

| model | fixed attack | frozen distance-3 order | gap |
| --- | ---: | ---: | ---: |
| Terra | 6.7% | 0.0% | +6.7pp |
| Claude | 76.7% | 0.0% | +76.7pp |
| Gemini | 93.3% | 0.0% | +93.3pp |
| Qwen | 100.0% | 0.0% | +100.0pp |

All four models have a nonzero equal-distance gap; for Qwen it is 100pp.
The identity of the permutation matters beyond its inversion count.

## Scope

This result does not estimate a delay-magnitude effect. The implementation
shows the model only the delivered order; simulated arrival times never enter
the prompt. The threat model uses delay as a means of inducing an order, while
this experiment estimates order effects only.

## Raw-evidence provenance

| model | reasoning | raw SHA-256 |
| --- | --- | --- |
| Terra | `none` | `02c8f61b79f94e5a683e695090da2a93c47dd79d33eaa65e8ef632e959b5803c` |
| Claude | `none` | `eb65e8fc1ce6af335521f285c22a413007f291fccebebacb39da8a11b8d0364f` |
| Gemini | `minimal` | `b6894e01a36f9b6baf94d886cb75fa0a2567635cbf3763022beb5c07adc86965` |
| Qwen | `low` | `3116014338a5a088c957897d3d314f4b8e9507b6f5696d88ce73b081c40b66a1` |
