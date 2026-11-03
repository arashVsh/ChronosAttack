# Round 2 G: B3 and C1 on the matched roster (2026-10-08)

Status: frozen before any call. Purpose: Arash (2026-10-08) wants tables with no
blank cells except Claude with reasoning on. The 5 September B3 (software release)
and C1 (microgrid) study ran only Terra and Claude with reasoning off.

## Design

- Scenarios, payloads, prompts, targets (B3: B, C1: C) and the per-scenario job
  matrix are those of the 5 September study, unchanged: 30 stateful pairs, 10
  stateless pairs, 10 simultaneous controls, 15 trials at 0, 1 and 2 inversions,
  15 barrier trials, 10 six-order consistency panels; 525 calls per scenario.
  Engine: `completion_protocol.py`, unmodified, on a private instance.
- New cells: Terra-low, Gemini-minimal, Qwen-low (temperature 1, 256-token cap,
  30 s timeout). Claude with reasoning off is the existing 5 September cell, which
  used the same settings. The 5 September Terra cell (reasoning off) stays as a
  sensitivity cell.
- Per model 420 trials and 1,050 calls; 1,260 trials and 3,150 calls in total.
- Analysis: the 5 September analysis (`analyze_completion_study.py` functions):
  exact McNemar on the 30 stateful pairs, Holm over the six new primary tests,
  plus the descriptive controls and defenses.

## Execution

As D/F: hash-frozen manifest, 30 shards per model, $0.60 hard ceiling per shard,
graceful stop, transport wait, rerun from scratch up to r3 with every attempt kept
and costed, parallel lanes per model, meter readings before and after each shard.
Expected cost about $5.
