# Cross-scenario analysis: baseline rate does not determine steerability

Generated deterministically by `kaggle/render_round2_reports.py` from the pinned raw JSONL files. Do not hand-edit numeric results.

This comparison is exploratory. Each cell followed its own frozen protocol, but
the cross-scenario synthesis was defined after the outcomes were known. B3 and C1
use three observations; tree4 uses four. C1 transfers a similar numerical tradeoff
geometry to another domain and is not the independent second scenario planned for
round two.

## All eight completed stateful cells

| model | scenario | observations | natural | attacked | change | exact p |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Terra | B3 | 3 | 16.7% | 100.0% | +83.3pp | 5.96e-08 |
| Terra | C1 | 3 | 33.3% | 86.7% | +53.3pp | 4.02e-04 |
| Terra | tree4 | 4 | 0.0% | 6.7% | +6.7pp | 0.5 |
| Claude | B3 | 3 | 20.0% | 90.0% | +70.0pp | 5.72e-06 |
| Claude | C1 | 3 | 13.3% | 66.7% | +53.3pp | 1.45e-04 |
| Claude | tree4 | 4 | 93.3% | 76.7% | -16.7pp | 0.125 |
| Gemini | tree4 | 4 | 46.7% | 93.3% | +46.7pp | 5.19e-04 |
| Qwen | tree4 | 4 | 0.0% | 100.0% | +100.0pp | 1.86e-09 |

## What survives the falsification

The seven-cell analysis originally proposed target-rate headroom as the
explanation: significant cells had mid-range natural baselines, while Terra
floored and Claude ceilinged on tree4. Qwen is the direct counterexample. It
has a 0% natural target rate, exactly like Terra, yet the same fixed order moves
it to 100%. Baseline position therefore does not determine steerability.

Model identity alone does not determine steerability either. Terra and Claude
show large positive changes in B3 and C1 but little or negative change in
tree4. The result is an interaction among endpoint, scenario and exact order,
not a stable ranking of model robustness. Baseline rate still constrains the
numerical range a target-rate difference can take, but it is not a mechanism
or sufficient predictor.

The position and inversion analyses provide descriptive localization, not a
replacement mechanism claim: schedules at the same inversion distance can
differ by 100pp, and tool-position effects differ sharply by model. The new
independent scenario is needed to test transfer without reusing this geometry.

## Provenance

The B3/C1 matrix is regenerated from historical confirmation batches plus three pinned JSONL ledgers and verifies 2,100/2,100 planned calls. It does not read `completion_results/analysis.json`. Tree4 provenance is listed below.

## Raw-evidence provenance

| model | reasoning | raw SHA-256 |
| --- | --- | --- |
| Terra | `none` | `02c8f61b79f94e5a683e695090da2a93c47dd79d33eaa65e8ef632e959b5803c` |
| Claude | `none` | `eb65e8fc1ce6af335521f285c22a413007f291fccebebacb39da8a11b8d0364f` |
| Gemini | `minimal` | `b6894e01a36f9b6baf94d886cb75fa0a2567635cbf3763022beb5c07adc86965` |
| Qwen | `low` | `3116014338a5a088c957897d3d314f4b8e9507b6f5696d88ce73b081c40b66a1` |
