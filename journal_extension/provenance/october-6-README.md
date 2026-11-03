# ChronosAttack round-two reproducibility packet

This package is an offline replay of the historical four-model results and the
round-two A, B, and C evidence available at the pinned collection snapshot.
Run from the extracted directory:

    python3 kaggle/round2_package/verify_packet.py

Supported, tested environment: CPython 3.13.5, NumPy 2.2.6, SciPy 1.16.2.
The verifier uses no model API or network access. It checks every payload
hash and path before the historical 46 checks, six strict round-two gates,
and independent A/B/C raw collection and report replay.

`PACKAGE.json` identifies the C snapshot and status. In the final packet
(2026-09-27) A, B and C are complete on Terra-low, Gemini-minimal, Qwen-low and
the Claude-none sensitivity cell; Claude's matched non-off cell is unavailable.
Five null-cost provider 429s in C are settled at zero by quota continuity
(procedure of 2026-09-25); raw bytes keep the null. One Qwen B shard was rerun
under a written note and its failed run is pinned and disclosed. D–F and
DeepSeek are deferred. Charged failed calls and known-cost lower bounds are included
in raw-derived accounting. Intermediate analysis JSON is checked output.

The sealed Gemini C platform bridges (s03 v2, s06 v2) and the Gemini s06 v1
settlement proof hash their full original Kaggle downloads. Their bytecode and lock files are included solely as pinned run
provenance; unrelated caches and notebook drafts are excluded.

This is a local reproducibility packet, not a publication or manuscript.
