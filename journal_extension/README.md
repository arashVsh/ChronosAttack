# ChronosAttack: source code, prompts, and raw model outputs

Supplementary material for the manuscript "ChronosAttack: Adversarial Tool Scheduling Attacks on LLM Agents"
(Masih Moafi and Arash Vashagh). It contains the experiment code, the task definitions and prompts, the executed
experiment notebooks with their raw model outputs, and the analysis code that recomputes every number in the paper.
No API keys or account credentials are included.

## 1. Reproduce the paper's numbers (no model calls, no keys)

Requirements: Python 3.13, NumPy 2.2, SciPy 1.16 (Matplotlib 3.10 for the figure scripts).
From this `journal_extension/` folder, run:

    python3 verify_current.py

The script blocks network access and makes no model calls. It checks the hashes of all raw outputs, recomputes
the per-order target rates, order-information statistics, significance tests, and defense results from the raw
logs, and compares them with the values reported in the manuscript.

## 2. Run the experiments again (your own model access)

The experiments ran as Kaggle notebooks with the `kaggle-benchmarks` library, which sends each prompt to the
selected model and records the reply.

- `kaggle/four_observation_protocol.py` and `kaggle/completion_protocol.py`: the agent loop (tool results
  delivered one at a time in a chosen order), the stateful and stateless settings, and the decision parsing.
- `kaggle/four_observation_defenses.py`: the four defenses.
- `kaggle/round2_generated/`: the generated notebook for each experiment cell (task, model, setting, seed).
- `kaggle/round2_runs_20260920/` and the other `*_results` folders: the executed notebooks and raw outputs.

To rerun a cell, upload its notebook to Kaggle under your own account, select the model, and run it.
Model access and any API keys or usage costs are the reviewer's own; the authors' keys are not needed.
To run outside Kaggle, replace the `kbench`/`llm` objects passed to `run(...)` with a client for your own
provider and API key. Model replies vary between runs, so rerun rates can differ from the reported rates
within sampling error.

## 3. Other contents

- `manuscript/`: an earlier version of the manuscript and `evidence-map.json`, which maps each table and figure
  to the files that produce it.
- `deliverables/final_report/tables/`: historical analysis tables kept for reproducibility.
- `provenance/`: run manifests.

The original-paper results (cloud backup and shipping partner) were taken from the earlier preprint
(https://doi.org/10.21203/rs.3.rs-10854515/v1) and are not rerun here.
