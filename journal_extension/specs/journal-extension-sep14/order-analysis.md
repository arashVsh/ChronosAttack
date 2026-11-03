# Held-out order selection and model-by-order regression

Generated deterministically by `kaggle/render_round2_reports.py` from the pinned raw JSONL files. Do not hand-edit numeric results.

## Frozen split-half analysis

Seed `20260920` produced selection repetitions 3, 4, 5, 7 and 10;
evaluation repetitions are 1, 2, 6, 8 and 9. The selected order maximizes
target-C rate in the selection half, with the lowest numeric condition as the
tie-break. Selection rows never enter evaluation.

| model | selected condition and order | selection C | tied maxima | held-out natural | held-out selected | change | gains/losses | exact p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Terra | 11: heat → cost → survival → equity | 1/5 | 3 | 0/5 | 1/5 | +20.0pp | 1/0 | 1 |
| Claude | 0: equity → heat → survival → cost | 5/5 | 5 | 3/5 | 3/5 | +0.0pp | 0/0 | 1 |
| Gemini | 6: heat → equity → survival → cost | 5/5 | 2 | 1/5 | 4/5 | +60.0pp | 3/0 | 0.25 |
| Qwen | 9: heat → survival → cost → equity | 5/5 | 10 | 0/5 | 5/5 | +100.0pp | 5/0 | 0.0625 |

These five-pair evaluations are descriptive. Even five gains and no losses
give a minimum two-sided exact p of 0.0625, observed for Qwen. The split
protects evaluation from order selection but does not create high power.

## Separation-resistant global model-by-order analysis

The raw 4×24 grid has 63 of 96 cells at 0% or 100%, so ordinary logistic
MLE/Wald inference is unsuitable. The frozen analysis uses Firth logistic
regression for `model * categorical_order`. The full interaction fit has
96 parameters; the additive
fit has 27. The single exploratory
global penalized likelihood-ratio assessment is
χ²(69) = 319.67, p = 6.41e-34.

The global comparison uses the full-model Jeffreys penalty under both the
interaction and additive fits. Its chi-square reference is exploratory and
not calibrated for this sparse finite sample.

Predictions below are separation-resistant cell probabilities with empirical
95% panel-resampling stability intervals from 2,000 resamples of complete
24-order panels within model. Repetition IDs are balanced-panel bookkeeping,
not subject or temporal identities. Boundary cells can have zero-width
intervals because a nonparametric bootstrap cannot generate an outcome absent
from all ten observed panels; these are not calibrated probability confidence
intervals.

| order | Terra | Claude | Gemini | Qwen |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 4.5% [4.5, 4.5] | 77.3% [50.0, 95.5] | 31.8% [4.5, 59.1] | 4.5% [4.5, 4.5] |
| 1 | 4.5% [4.5, 4.5] | 95.5% [95.5, 95.5] | 4.5% [4.5, 4.5] | 4.5% [4.5, 4.5] |
| 2 | 4.5% [4.5, 4.5] | 86.4% [68.2, 95.5] | 4.5% [4.5, 4.5] | 4.5% [4.5, 4.5] |
| 3 | 4.5% [4.5, 4.5] | 68.2% [40.9, 95.5] | 13.6% [4.5, 31.8] | 4.5% [4.5, 4.5] |
| 4 | 4.5% [4.5, 4.5] | 13.6% [4.5, 31.8] | 4.5% [4.5, 4.5] | 4.5% [4.5, 4.5] |
| 5 | 4.5% [4.5, 4.5] | 4.5% [4.5, 4.5] | 4.5% [4.5, 4.5] | 4.5% [4.5, 4.5] |
| 6 | 4.5% [4.5, 4.5] | 95.5% [95.5, 95.5] | 86.4% [68.2, 95.5] | 31.8% [4.5, 59.1] |
| 7 | 4.5% [4.5, 4.5] | 77.3% [50.0, 95.5] | 68.2% [40.9, 95.5] | 4.5% [4.5, 4.5] |
| 8 | 13.6% [4.5, 31.8] | 95.5% [95.5, 95.5] | 95.5% [95.5, 95.5] | 4.5% [4.5, 4.5] |
| 9 | 4.5% [4.5, 4.5] | 77.3% [50.0, 95.5] | 86.4% [68.2, 95.5] | 95.5% [95.5, 95.5] |
| 10 | 4.5% [4.5, 4.5] | 59.1% [31.8, 86.4] | 4.5% [4.5, 4.5] | 95.5% [95.5, 95.5] |
| 11 | 22.7% [4.5, 50.0] | 86.4% [68.2, 95.5] | 4.5% [4.5, 4.5] | 95.5% [95.5, 95.5] |
| 12 | 4.5% [4.5, 4.5] | 77.3% [50.0, 95.5] | 4.5% [4.5, 4.5] | 4.5% [4.5, 4.5] |
| 13 | 4.5% [4.5, 4.5] | 31.8% [4.5, 59.1] | 22.7% [4.5, 50.0] | 4.5% [4.5, 4.5] |
| 14 | 4.5% [4.5, 4.5] | 95.5% [95.5, 95.5] | 4.5% [4.5, 4.5] | 4.5% [4.5, 4.5] |
| 15 | 4.5% [4.5, 4.5] | 68.2% [40.9, 95.5] | 4.5% [4.5, 4.5] | 95.5% [95.5, 95.5] |
| 16 | 4.5% [4.5, 4.5] | 59.1% [31.8, 86.4] | 4.5% [4.5, 4.5] | 95.5% [95.5, 95.5] |
| 17 | 13.6% [4.5, 31.8] | 86.4% [68.2, 95.5] | 4.5% [4.5, 4.5] | 95.5% [95.5, 95.5] |
| 18 | 4.5% [4.5, 4.5] | 4.5% [4.5, 4.5] | 4.5% [4.5, 4.5] | 68.2% [40.9, 95.5] |
| 19 | 4.5% [4.5, 4.5] | 4.5% [4.5, 4.5] | 13.6% [4.5, 31.8] | 40.9% [13.6, 68.2] |
| 20 | 4.5% [4.5, 4.5] | 50.0% [22.7, 77.3] | 4.5% [4.5, 4.5] | 95.5% [95.5, 95.5] |
| 21 | 31.8% [4.5, 59.1] | 59.1% [31.8, 86.4] | 4.5% [4.5, 4.5] | 95.5% [95.5, 95.5] |
| 22 | 4.5% [4.5, 4.5] | 77.3% [50.0, 95.5] | 4.5% [4.5, 4.5] | 86.4% [68.2, 95.5] |
| 23 | 13.6% [4.5, 31.8] | 68.2% [40.9, 95.5] | 4.5% [4.5, 4.5] | 95.5% [95.5, 95.5] |

The global p-value is an uncalibrated asymptotic exploratory assessment. The
cell probabilities and empirical stability intervals are the primary
regression outputs; no
catalogue of interaction-coefficient Wald p-values is reported.

## Raw-evidence provenance

| model | reasoning | raw SHA-256 |
| --- | --- | --- |
| Terra | `none` | `02c8f61b79f94e5a683e695090da2a93c47dd79d33eaa65e8ef632e959b5803c` |
| Claude | `none` | `eb65e8fc1ce6af335521f285c22a413007f291fccebebacb39da8a11b8d0364f` |
| Gemini | `minimal` | `b6894e01a36f9b6baf94d886cb75fa0a2567635cbf3763022beb5c07adc86965` |
| Qwen | `low` | `3116014338a5a088c957897d3d314f4b8e9507b6f5696d88ce73b081c40b66a1` |
