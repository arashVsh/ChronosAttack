# Which observation matters: model-specific position effects

Generated deterministically by `kaggle/render_round2_reports.py` from the pinned raw JSONL files. Do not hand-edit numeric results.

The complete stateful permutation panels contain ten repetitions of all 24
orders. Each tool therefore appears first and last 60 times per model. Rates
below are target-C choice; intervals resample complete 24-order panels and are
pointwise exploratory intervals.

| model | tool | first | last | last − first | panel bootstrap 95% |
| --- | --- | ---: | ---: | ---: | ---: |
| Terra | equity | 0.0% | 11.7% | +11.7pp | [5.0, 18.3] |
| Terra | heat | 5.0% | 0.0% | -5.0pp | [-11.7, 0.0] |
| Terra | survival | 1.7% | 0.0% | -1.7pp | [-5.0, 0.0] |
| Terra | cost | 6.7% | 1.7% | -5.0pp | [-10.0, 0.0] |
| Claude | equity | 58.3% | 76.7% | +18.3pp | [8.3, 26.7] |
| Claude | heat | 85.0% | 40.0% | -45.0pp | [-55.0, -35.0] |
| Claude | survival | 71.7% | 50.0% | -21.7pp | [-33.3, -8.3] |
| Claude | cost | 43.3% | 91.7% | +48.3pp | [38.3, 60.0] |
| Gemini | equity | 6.7% | 15.0% | +8.3pp | [3.3, 13.3] |
| Gemini | heat | 58.3% | 6.7% | -51.7pp | [-60.0, -41.7] |
| Gemini | survival | 3.3% | 11.7% | +8.3pp | [3.3, 13.3] |
| Gemini | cost | 1.7% | 36.7% | +35.0pp | [28.3, 41.7] |
| Qwen | equity | 0.0% | 100.0% | +100.0pp | [100.0, 100.0] |
| Qwen | heat | 55.0% | 38.3% | -16.7pp | [-23.3, -10.0] |
| Qwen | survival | 50.0% | 45.0% | -5.0pp | [-10.0, -1.7] |
| Qwen | cost | 83.3% | 5.0% | -78.3pp | [-86.7, -68.3] |

## Interpretation

Position effects are large but heterogeneous. Claude and Gemini show large
negative heat effects and positive cost effects. Qwen reverses the simple
cost-last account: equity changes from 0% first to 100% last, while cost
changes from 83.3% first to 5.0% last. No single recency rule or tool-level
mechanism generalizes across all four endpoints.

The stable conclusion is that tool identity and position interact. This
complements the equal-distance result: two schedules can be equally displaced
while assigning very different positions to the observations that matter for a
particular model. It is a behavioral pattern, not evidence of an internal
cognitive mechanism.

## Raw-evidence provenance

| model | reasoning | raw SHA-256 |
| --- | --- | --- |
| Terra | `none` | `02c8f61b79f94e5a683e695090da2a93c47dd79d33eaa65e8ef632e959b5803c` |
| Claude | `none` | `eb65e8fc1ce6af335521f285c22a413007f291fccebebacb39da8a11b8d0364f` |
| Gemini | `minimal` | `b6894e01a36f9b6baf94d886cb75fa0a2567635cbf3763022beb5c07adc86965` |
| Qwen | `low` | `3116014338a5a088c957897d3d314f4b8e9507b6f5696d88ce73b081c40b66a1` |
