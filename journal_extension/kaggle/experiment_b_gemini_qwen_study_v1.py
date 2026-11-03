"""Gemini-minimal and Qwen-low B study shards under the 2026-09-26 transport-wait amendment.

The source is the unchanged ``build_experiment_b_hosted_v1.build_source`` output for the
setting's passed replacement pilot, plus one wrapper after ``max_retries=0`` that waits out
provider HTTP 429s below the evidence layer (same rule as the C amendment of 2026-09-25).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import build_experiment_b_hosted_v1 as builder
import experiment_c_provider_429_v1 as c_policy

ROOT = Path(__file__).resolve().parent.parent
GENERATED = ROOT / "kaggle/round2_generated"
PILOTS = ROOT / "kaggle/round2_runs_20260920/experiment_b_pilot"
PROCEDURE = "specs/journal-extension-sep14/round2-b-gemini-qwen-study-transport-wait-amendment-2026-09-26.md"
SETTINGS = {
    "gemini-minimal": ("google/gemini-3.6-flash", "gemini-3.6-flash/3230348"),
    "qwen-low": ("qwen/qwen3-235b-a22b-instruct-2507", "qwen3-235b-a22b-instruct-2507/3230352"),
}
REPLACEMENT_NOTE = "specs/journal-extension-sep14/round2-b-qwen-s25-replacement-note-2026-09-26.md"
REPLACEMENTS = {("qwen-low", 25, 1)}  # (setting, shard, rerun) approved by REPLACEMENT_NOTE
TRANSPORT_POLICY = {
    **{key: value for key, value in c_policy.TRANSPORT_POLICY.items() if key not in ("schema", "procedure")},
    "schema": "chronos.experiment-b-transport-wait.v1",
    "procedure": PROCEDURE,
}
_CLIENT_ANCHOR = "    llm.client = llm.client.with_options(max_retries=0)\n"
_WAIT_WRAPPER = (c_policy._WAIT_WRAPPER
                 .replace("    _policy = CONTRACT['transport_policy']\n",
                          f"    _policy = {TRANSPORT_POLICY!r}\n")
                 .replace("OUTPUT / 'transient_waits.json'", "output / 'transient_waits.json'"))


def names(setting: str, shard: int, rerun: int = 0) -> tuple[str, str, Path]:
    """``rerun`` > 0 names a from-scratch replacement shard (see REPLACEMENT_NOTE)."""
    us = setting.replace("-", "_")
    r = f"r{rerun}" if rerun else ""
    return (f"chronos-r2-tree4-rotation-study-{setting}-s{shard:02d}{'-' * bool(r)}{r}-v1",
            f"round2_tree4_rotation_study_{us}_s{shard:02d}{'_' * bool(r)}{r}_v1",
            GENERATED / f"tree4_rotation_study_{us}_s{shard:02d}{'_' * bool(r)}{r}_v1.py")


def pilot(setting: str) -> dict:
    model, run = SETTINGS[setting]
    us = setting.replace("-", "_")
    out = (PILOTS / setting / f"chronos-r2-tree4-rotation-pilot-{setting}-v2/1" / run
           / f"round2_tree4_rotation_pilot_{us}_v2")
    return {
        "model": model,
        "receipt": json.loads((GENERATED / f"experiment_b_pilot_receipt_{us}_v2.json").read_text()),
        "evidence": (out / (model.replace("/", "_") + ".jsonl")).read_bytes(),
        "terminal": (out / "terminal.json").read_bytes(),
        "intended": (out / "intended_manifest.json").read_bytes(),
    }


def build_source(setting: str, shard: int, rerun: int = 0) -> str:
    if rerun and (setting, shard, rerun) not in REPLACEMENTS:
        raise ValueError("replacement shard is not covered by a written note")
    task, folder, _ = names(setting, shard, rerun)
    p = pilot(setting)
    source = builder.build_source(
        model=p["model"], phase="study", task_name=task, output_folder=folder,
        ceiling_usd=builder.study_ceiling_from_pilot(p["receipt"]), shard_index=shard,
        pilot_receipt=p["receipt"], pilot_evidence=p["evidence"],
        pilot_terminal=p["terminal"], pilot_intended=p["intended"])
    for old, new in (("import sys\n", "import sys\nimport time\n"), (_CLIENT_ANCHOR, _WAIT_WRAPPER)):
        if source.count(old) != 1:
            raise ValueError(f"frozen B source anchor not unique: {old!r}")
        source = source.replace(old, new)
    compile(source, "b_study_transport_wait.py", "exec")
    return source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("setting", choices=sorted(SETTINGS))
    parser.add_argument("shard", type=int)
    parser.add_argument("--rerun", type=int, default=0)
    args = parser.parse_args()
    task, _, path = names(args.setting, args.shard, args.rerun)
    source = build_source(args.setting, args.shard, args.rerun)
    if path.exists():
        if path.read_text() != source:
            raise SystemExit(f"{path} exists and differs from regeneration")
    else:
        path.write_text(source)
    print(task, path.relative_to(ROOT), c_policy.sha256(source.encode()))


if __name__ == "__main__":
    main()
