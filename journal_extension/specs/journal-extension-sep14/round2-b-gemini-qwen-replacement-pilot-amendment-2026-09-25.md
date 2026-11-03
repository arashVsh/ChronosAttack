# Experiment B: one replacement pilot for Gemini and Qwen, 2026-09-25

Status: **sealed before any replacement call.** It changes no fixture, rotation,
label mapping, model, reasoning setting, call setting, token cap, job, sample
size, endpoint, exclusion or analysis. It only replaces the stop rule that
`round2-b-pilot-failure-and-cost-disposition-2026-09-23.md` applied to two
settings after a single failed pilot call each.

## Why

Arash's plan of 20 September asks for label rotation on all four models. It
matters most for Gemini and Qwen, the two models the fixed attack steers:
rotation is the test of whether that steering comes from evidence order or a
letter preference. The original pilots stopped on provider-side events, not on
a protocol or code fault: Gemini's first call returned HTTP 429 (heavy load);
Qwen returned malformed/truncated JSON on its fourth call. Both models have
since completed Experiment C shards at the same settings (Gemini-minimal 36 jobs,
Qwen-low 13 jobs), so the earlier stop is not evidence that the cells cannot run.

## Rule

1. Each of Gemini-minimal and Qwen-low gets **exactly one** replacement pilot:
   the same frozen rotation-1 natural/attack pair, the same `$0.25` ceiling, no
   SDK retries, built by the unchanged `build_experiment_b_hosted_v1.py` under a
   new task name `chronos-r2-tree4-rotation-pilot-<setting>-v2` and output folder
   `round2_tree4_rotation_pilot_<setting>_v2`. It starts from an empty ledger:
   pilot outcomes are excluded from the study by the frozen design, so no study
   data is replayed.
2. A replacement pilot passes only through the unchanged
   `issue_experiment_b_pilot_receipt_v1.py` gate from its downloaded raw ledger.
   A pass authorizes that setting's frozen 30-shard study with the ceiling the
   frozen rule derives from the pilot's telemetry. If the pilot stops on a
   provider HTTP 429 whose zero charge is shown by the signed-in quota readings
   around it (monthly change equal to the raw known cost), it is a transport
   event, not a pilot result: a fresh pilot (`-v3`, then `-v4`) may run, at most
   three replacement attempts in total, each from an empty ledger. Any other
   failure (for example malformed or truncated output, a charged error, or a
   source/audit mismatch) makes the setting permanently unavailable for B.
   Launches are scheduled in low-load hours where possible (the observed 429s
   fell between 07:58 and 17:37 UTC).
3. The original failed pilots, their null costs and the unallocated meter
   residual stay exactly as recorded. Unknown cost remains unknown.
4. Launches stay serial with Experiment C: no B task runs while a C shard is
   between its prebuild quota reading and its post-run reading, so every
   quota delta remains attributable. Each B launch window takes a fresh signed-in
   quota reading before and after.
5. Any completed Gemini or Qwen B cell is analysed with the frozen B analysis,
   and reports disclose that it ran under this amendment, after the Terra and
   Claude-none cells.

## Pinned replacement sources

Generated offline before any replacement call; each differs from its frozen v1
pilot source only in the task name and output folder (six lines).

- `kaggle/round2_generated/tree4_rotation_pilot_gemini_minimal_v2.py`: SHA-256 `073a0b7c2ffc40750d82ecf5c066d1acd366272a9da2529a1bf91b78ffa5876a`
- `kaggle/round2_generated/tree4_rotation_pilot_qwen_low_v2.py`: SHA-256 `6e4f982e43ae026ed2239ad06d1830f685084c34b37fda45644653cf55c80bfb`
