# Experiment B: Gemini/Qwen study shards with the transport-level wait, 2026-09-26

Status: **sealed before any Gemini-minimal or Qwen-low B study call.** No fixture,
rotation, label mapping, model, reasoning setting, call setting, token cap, job,
shard partition, sample size, ceiling rule, endpoint, exclusion or analysis
changes. Terra-low and Claude-none B cells are complete and untouched.

## Why

Both replacement pilots passed on 26 September (Gemini run 3230348, $0.00882675;
Qwen run 3230352, $0.00244112; each 2/2 jobs, 10/10 calls, no failures, and the
signed-in monthly quota change equal to the raw cost). That authorizes each
setting's frozen 30-shard study
(`round2-b-gemini-qwen-replacement-pilot-amendment-2026-09-25.md`).

These are the same two providers whose HTTP 429 "heavy load" refusals were
stopping Experiment C shards. The frozen B runtime, like C's, lets such a
refusal end the shard. The fix is the one already sealed for C
(`experiment-c-transport-wait-amendment-2026-09-25.md`) and used in the
four-model matrix ("Retry BELOW the evidence layer"): a refused request carries
no model response, so waiting it out is a transport event, not a trial.

## Rule

1. Each shard's source is the unchanged `build_experiment_b_hosted_v1.build_source`
   output (study phase, the setting's v2 pilot receipt and raw pilot artifacts,
   the frozen pilot-derived ceiling), plus `import time` and one wrapper right
   after `llm.client = llm.client.with_options(max_retries=0)`. It is generated
   by `kaggle/experiment_b_gemini_qwen_study_v1.py`. The wrapper, its policy
   literal (`chronos.experiment-b-transport-wait.v1`) and its limits are those
   of the C amendment: wait only on `RateLimitError`, 20 s doubling to 300 s, at
   most 1,800 s per call, SDK retries still 0. Every other error is unchanged.
2. Waits are counted in `transient_waits.json` in the output folder, never in the
   raw ledger. A call still refused after 1,800 s is recorded exactly as before.
3. Task names are `chronos-r2-tree4-rotation-study-<setting>-sNN-v1`. Shards run
   serially with Experiment C (amendment of 2026-09-25, rule 4). Each has a
   fresh signed-in quota reading before and after. Its monthly change must equal
   the raw known cost. Every shard must pass the frozen
   `verify_experiment_b_collection.verify_raw_study_shard` replay.
4. A shard that does not complete is not rerun from scratch. It is recorded as
   is, and any resume uses the frozen B `--resume-from` path under a separate
   written note.
5. The completed cells are sealed with Terra-low and Claude-none in a v2 B
   collection. They are analysed with the frozen B cell analysis, and reports
   disclose that they ran under this amendment and the replacement-pilot
   amendment.
