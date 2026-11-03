"""Regenerate and verify every staged Terra reasoning-on study shard."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from build_hosted_cell_v2 import build_source, plan_cell


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
MODEL = "openai/gpt-5.6-terra"
REASONING = "low"
STUDY_ID = "chronos_round2_terra_reasoning_study_low_v1"
SHARD_COUNT = 10
CEILING_USD = 0.95
MINIMAL = (
    HERE
    / "round2_runs_20260920/terra_minimal/chronos-r2-terra-preflight-minimal-v1/1"
    / "gpt-5.6-terra/2644337/round2_terra_reasoning_preflight_minimal_v1"
)
LOW = (
    HERE
    / "round2_runs_20260920/terra_low/chronos-r2-terra-preflight-low-v1/1"
    / "gpt-5.6-terra/2646426/round2_terra_reasoning_preflight_low_v1"
)


def _assignments(source: str, path: Path) -> dict:
    values = {}
    for node in ast.parse(source, str(path)).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    values[target.id] = ast.literal_eval(node.value)
                except (TypeError, ValueError):
                    pass
    return values


def _arguments(index: int) -> dict:
    suffix = f"s{index:02d}_v1"
    return {
        "kind": "study",
        "model": MODEL,
        "reasoning": REASONING,
        "study_id": STUDY_ID,
        "ceiling_usd": CEILING_USD,
        "task_name": f"chronos-r2-terra-study-low-{suffix.replace('_', '-')}",
        "output_folder": f"round2_terra_reasoning_study_low_{suffix}",
        "shard_index": index,
        "shard_count": SHARD_COUNT,
        "preflight_receipt": LOW / "reasoning_receipt.json",
        "preflight_evidence": LOW / "openai_gpt-5.6-terra.jsonl",
        "preflight_terminal": LOW / "reasoning_terminal.json",
        "minimal_unsupported_receipt": MINIMAL / "reasoning_receipt.json",
        "minimal_unsupported_evidence": MINIMAL / "openai_gpt-5.6-terra.jsonl",
        "minimal_unsupported_terminal": MINIMAL / "reasoning_terminal.json",
        "minimal_unsupported_quota_attestation": MINIMAL / "quota_attestation_1.json",
    }


def verify() -> list[dict]:
    expected_paths = {
        GENERATED / f"terra_study_low_s{index:02d}_v1.py"
        for index in range(SHARD_COUNT)
    }
    # Shards 06--09 were relaunched under fresh outer task names after Kaggle
    # created source-less task shells.  They are separately byte- and
    # artifact-verified by verify_round2_terra_study_collection.py.  Keep this
    # verifier focused on the ten original frozen partition sources while
    # still rejecting every filename outside that explicit, known set.
    relaunch_paths = {
        GENERATED / f"terra_study_low_s{index:02d}_relaunch_v1.py"
        for index in range(6, 10)
    }
    actual_paths = set(GENERATED.glob("terra_study_low_s*_v1.py"))
    if actual_paths != expected_paths | relaunch_paths:
        raise ValueError("staged Terra study shard filenames are incomplete or unexpected")

    full = plan_cell(
        kind="study", model=MODEL, reasoning=REASONING, study_id=STUDY_ID
    )["jobs"]
    expected_ids = {job["id"] for job in full}
    observed_ids = []
    checked = []
    for index, path in enumerate(sorted(expected_paths)):
        expected_source = build_source(**_arguments(index))
        raw = path.read_bytes()
        source = raw.decode("utf-8")
        if source != expected_source:
            raise ValueError(f"staged shard is not byte-exact regeneration: {path.name}")
        compile(source, str(path), "exec")
        values = _assignments(source, path)
        contract = values["CONTRACT"]
        jobs = values["EXPECTED_JOBS"]
        if (
            values["MODEL"] != MODEL
            or values["REASONING"] != REASONING
            or values["STUDY_ID"] != STUDY_ID
            or values["KIND"] != "study"
            or values["INCREMENTAL_CEILING_USD"] != CEILING_USD
            or values["MAX_WAIT_SECONDS"] != 7200
            or values["RESUME_LEDGER"] != b""
            or contract["shard_index"] != index
            or contract["shard_count"] != SHARD_COUNT
            or contract["incremental_ceiling_usd"] != CEILING_USD
            or contract["effective_ceiling_usd"] != CEILING_USD
            or contract["accepted_preflight_receipt_sha256"]
            != "77d2b0eee32b20e66d2bd203c00a011d40184c482b0b2bf1d11aea436f5f7467"
            or contract["minimal_unsupported_receipt_sha256"]
            != "4e6e9f30bc1803e087ba434b0ce049723567530be10ade9c1569199138d01b2a"
        ):
            raise ValueError(f"staged shard contract mismatch: {path.name}")
        observed_ids.extend(job["id"] for job in jobs)
        checked.append(
            {
                "path": str(path.relative_to(HERE.parent)),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "jobs": len(jobs),
                "calls": sum(job["calls"] for job in jobs),
                "shard_index": index,
            }
        )
    if (
        len(observed_ids) != len(set(observed_ids))
        or set(observed_ids) != expected_ids
        or sum(item["jobs"] for item in checked) != 690
        or sum(item["calls"] for item in checked) != 2310
    ):
        raise ValueError("study shards are not a disjoint, exhaustive full-cell partition")
    return checked


def main() -> None:
    checked = verify()
    for item in checked:
        print(
            f"PASS shard {item['shard_index']:02d}: {item['jobs']} jobs / "
            f"{item['calls']} calls {item['sha256']}"
        )
    print("ROUND2 TERRA STUDY VERIFIED: 10 shards, 690 jobs, 2310 calls")


if __name__ == "__main__":
    main()
