# Decision trajectories: persistence and revision

Generated deterministically by `kaggle/render_round2_reports.py` from the pinned raw JSONL files. Do not hand-edit numeric results.

This analysis reuses provisional choices already recorded in stateful trials.
It describes decision persistence and revision; it does not identify an internal
anchoring mechanism.

## Revision behavior

| model | arm | trials | mean revisions | final = first | never revised | returned to first | synthesis changed |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Terra | stateful natural/attack pairs | 60 | 0.97 | 20.0% | 16.7% | 3.3% | 0.0% |
| Terra | 24-order panels | 240 | 1.02 | 59.6% | 40.4% | 19.2% | 0.0% |
| Claude | stateful natural/attack pairs | 60 | 1.38 | 46.7% | 46.7% | 0.0% | 10.0% |
| Claude | 24-order panels | 240 | 1.35 | 35.8% | 16.7% | 19.2% | 6.7% |
| Gemini | stateful natural/attack pairs | 60 | 1.73 | 23.3% | 23.3% | 0.0% | 0.0% |
| Gemini | 24-order panels | 240 | 1.09 | 50.4% | 29.2% | 21.2% | 0.0% |
| Qwen | stateful natural/attack pairs | 60 | 2.00 | 0.0% | 0.0% | 0.0% | 0.0% |
| Qwen | 24-order panels | 240 | 2.19 | 16.2% | 0.0% | 16.2% | 4.6% |

## First departure from the initial choice in the 24-order panels

| model | step 2 | step 3 | step 4 | step 5 | never departed |
| --- | ---: | ---: | ---: | ---: | ---: |
| Terra | 99 | 41 | 3 | 0 | 97 |
| Claude | 113 | 48 | 35 | 4 | 40 |
| Gemini | 104 | 52 | 14 | 0 | 70 |
| Qwen | 200 | 40 | 0 | 0 | 0 |

Revision remains front-loaded across all four models. Qwen strengthens that
description—every panel trial departs by step 2 or 3—but it also revises more
often overall (2.19 transitions per panel trial). Final synthesis changes are
rare rather than universally absent: 0% for Terra and Gemini, 6.7% for Claude
and 4.6% for Qwen in the permutation panels.

These records locate when observable choices change. They do not show why the
model changed or justify claims about hidden reasoning state.

## Raw-evidence provenance

| model | reasoning | raw SHA-256 |
| --- | --- | --- |
| Terra | `none` | `02c8f61b79f94e5a683e695090da2a93c47dd79d33eaa65e8ef632e959b5803c` |
| Claude | `none` | `eb65e8fc1ce6af335521f285c22a413007f291fccebebacb39da8a11b8d0364f` |
| Gemini | `minimal` | `b6894e01a36f9b6baf94d886cb75fa0a2567635cbf3763022beb5c07adc86965` |
| Qwen | `low` | `3116014338a5a088c957897d3d314f4b8e9507b6f5696d88ce73b081c40b66a1` |
