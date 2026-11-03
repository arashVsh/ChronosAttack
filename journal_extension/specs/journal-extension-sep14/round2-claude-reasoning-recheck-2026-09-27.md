# Round 2: Claude lowest non-off reasoning, recheck (2026-09-27)

Written before any recheck call. Masih directed this recheck on 2026-09-27.

## Why

On 2026-09-20 the Claude `minimal` preflight was tried twice, at 12:34 and
17:43 UTC. Both times the first request returned a generic HTTP 500 ("An
internal server error occurred.", `server_error`). No answer came back and
nothing was charged. The 09-20 retry amendment allowed one replacement, then
classified Claude as operationally unavailable. `low` was never tried. A generic
500 is not evidence that a setting is unsupported. It may be transient, so the
cell is rechecked a week later.

## Rule

1. Each recheck round runs the unchanged frozen preflight (2 jobs, 10 calls,
   `build_hosted_cell_v2`, attempt 1 only, SDK retries 0, $0.25 ceiling).
   It runs at `minimal`. `low` can run only after an explicit rejection of
   `minimal` (rule 4), because the frozen builder requires a
   minimal-unsupported receipt before it builds `low`. Task names are
   `chronos-r2-claude-preflight-<setting>-r<k>-v1`, where k is the round number
   (the 09-20 runs count as round 1 for `minimal`).
2. Rounds are spaced out: now, then about 3 h, 8 h and 24 h later. That makes
   at most four rounds, and the branch stops for good after that.
3. The first passing setting is selected. A pass issues the usual receipt
   through the existing strict preflight gate.
4. An explicit 400/422 rejection naming `minimal` as unsupported ends `minimal`
   for good. `low` is then the only candidate.
5. Each round has signed-in quota readings before and after. Any null-cost call
   is settled only by those readings. It is never assumed to be zero.
6. If a setting passes, Claude's A, B and C cells at that setting run as their
   own later step under the existing full-cell gates, within the daily free
   credit. The Claude-none cells stay what they are: a sensitivity.

## Result, 2026-09-27 02:44–04:03 UTC

- Round 2 `minimal` preflight (`chronos-r2-claude-preflight-minimal-r2-v1`):
  first request HTTP 500 again, as on 09-20.
- Private diagnostic task `chronos-claude-reasoning-diag-20260927` (versions 2–3; not study
  evidence; source in `kaggle/reasoning_probe_20260927/`). In the same runs:
  `minimal` failed with HTTP 500 at a 256- and a 4096-token cap, with and without
  structured output (4/4). `low` passed with structured output at the study's exact
  settings (256 tokens, temperature 1, 30 s) 3/3, and at 4096 tokens 2/2.
  `none` passed.
- Conclusion: on Kaggle, Claude `minimal` fails deterministically, and Kaggle reports
  it as a generic 500 instead of a 400. `low` works. The 09-20 "operationally
  unavailable" classification was premature: `low` was never reached, because the
  rules required an explicit 400 before trying it.
- Kaggle credit: $91.09 of $100 used this month (refills 2026-10-04 06:27 UTC).
  Claude-low A, B and C need roughly $25–35, which is more than remains.
