"""Seal the complete 30-shard Qwen Experiment A cell."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
from functools import lru_cache
import json
import math
from pathlib import Path

from round2_hosted import manifest_digest
import verify_experiment_a_qwen_batch00_collection as batch00
import verify_experiment_a_qwen_batch01_collection as batch01
import verify_experiment_a_qwen_batch02_collection as batch02
import verify_experiment_a_qwen_batch03_collection as batch03
import verify_experiment_a_qwen_batch04_collection as batch04
import water_supply_protocol as protocol


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
MANIFEST = GENERATED / "experiment_a_qwen_cell_collection_v1.json"
FROZEN_AT = "2026-09-21T00:11:24+03:30"
PRE_CELL_KNOWN_DAILY_COST_USD = 8.64577417
CELL_KNOWN_COST_USD = 0.57997258
POST_CELL_KNOWN_DAILY_COST_USD = 9.22574675

BATCHES = (
    ("batch00", batch00, tuple(range(0, 8))),
    ("batch01", batch01, tuple(range(8, 15))),
    ("batch02", batch02, tuple(range(15, 21))),
    ("batch03", batch03, tuple(range(21, 26))),
    ("batch04", batch04, tuple(range(26, 30))),
)


@lru_cache(maxsize=1)
def _sealed_batches() -> tuple[dict, ...]:
    # The final verifier recursively verifies batches 03, 02, 01, and 00,
    # including every raw hosted ledger and every technical relaunch proof.
    final = batch04.verify()
    if (
        final["cumulative_completed_jobs"] != 690
        or final["remaining_jobs"] != 0
    ):
        raise ValueError("final Qwen batch does not seal a complete cell")
    batch00._require_equal(
        final["post_batch_known_daily_cost_usd"],
        POST_CELL_KNOWN_DAILY_COST_USD,
        "final Qwen cumulative known cost",
    )
    return tuple(module._load_manifest(None) for _, module, _ in BATCHES)


def _manifest_hash(manifest: dict) -> str:
    return batch00._canonical_hash(
        {
            key: value
            for key, value in manifest.items()
            if key != "cell_collection_manifest_sha256"
        }
    )


def _full_jobs() -> list[dict]:
    previous = batch00._runtime()
    try:
        jobs = protocol.jobs_for(batch00.MODEL, "study")
    finally:
        batch00._restore_runtime(previous)
    return jobs


def _batch_record(
    label: str,
    module,
    expected_shards: tuple[int, ...],
    manifest: dict,
) -> dict:
    shards = sorted(manifest["shards"], key=lambda item: item["shard_index"])
    shard_indices = [item["shard_index"] for item in shards]
    if shard_indices != list(expected_shards):
        raise ValueError(f"{label} shard range changed")
    execution_kinds = Counter(item["execution_kind"] for item in shards)
    if "superseded_no_runs" in manifest:
        superseded_no_run_count = len(manifest["superseded_no_runs"])
    elif "superseded_no_run" in manifest:
        superseded_no_run_count = 1
    else:
        superseded_no_run_count = 0
    return {
        "label": label,
        "collection_manifest": batch00._file_record(module.MANIFEST),
        "collection_manifest_sha256": manifest[
            "collection_manifest_sha256"
        ],
        "shard_indices": shard_indices,
        "shard_count": manifest["shard_count"],
        "job_count": manifest["job_count"],
        "planned_calls": manifest["planned_calls"],
        "observed_invocations": manifest["totals"]["observed_invocations"],
        "complete_calls": manifest["totals"]["complete_calls"],
        "failed_calls": manifest["totals"]["failed_calls"],
        "unknown_cost_calls": manifest["totals"]["unknown_cost_calls"],
        "invalid_json_lines": manifest["totals"]["invalid_json_lines"],
        "events": manifest["totals"]["events"],
        "started_attempts": manifest["totals"]["started_attempts"],
        "known_cost_usd": manifest["totals"]["batch_known_cost_usd"],
        "pre_batch_known_daily_cost_usd": manifest["totals"][
            "pre_batch_known_daily_cost_usd"
        ],
        "post_batch_known_daily_cost_usd": manifest["totals"][
            "post_batch_known_daily_cost_usd"
        ],
        "execution_kinds": dict(sorted(execution_kinds.items())),
        "superseded_no_run_count": superseded_no_run_count,
    }


def build_manifest() -> dict:
    batch_manifests = _sealed_batches()
    records = [
        _batch_record(label, module, shards, manifest)
        for (label, module, shards), manifest in zip(
            BATCHES, batch_manifests
        )
    ]
    full_jobs = _full_jobs()
    all_shards = [
        shard for record in records for shard in record["shard_indices"]
    ]
    if all_shards != list(range(30)) or len(set(all_shards)) != 30:
        raise ValueError("Qwen batch manifests are not an exact 0--29 partition")
    for previous, current in zip(records, records[1:]):
        batch00._require_equal(
            previous["post_batch_known_daily_cost_usd"],
            current["pre_batch_known_daily_cost_usd"],
            "Qwen batch cost chain",
        )
    totals = {
        "shards": sum(record["shard_count"] for record in records),
        "jobs": sum(record["job_count"] for record in records),
        "planned_calls": sum(record["planned_calls"] for record in records),
        "observed_invocations": sum(
            record["observed_invocations"] for record in records
        ),
        "complete_calls": sum(record["complete_calls"] for record in records),
        "failed_calls": sum(record["failed_calls"] for record in records),
        "unknown_cost_calls": sum(
            record["unknown_cost_calls"] for record in records
        ),
        "invalid_json_lines": sum(
            record["invalid_json_lines"] for record in records
        ),
        "events": sum(record["events"] for record in records),
        "started_attempts": sum(
            record["started_attempts"] for record in records
        ),
        "known_cost_usd": round(
            math.fsum(record["known_cost_usd"] for record in records), 12
        ),
        "pre_cell_known_daily_cost_usd": records[0][
            "pre_batch_known_daily_cost_usd"
        ],
        "post_cell_known_daily_cost_usd": records[-1][
            "post_batch_known_daily_cost_usd"
        ],
        "technical_relaunches": sum(
            count
            for record in records
            for kind, count in record["execution_kinds"].items()
            if kind != "baseline"
        ),
        "superseded_no_run": sum(
            record["superseded_no_run_count"] for record in records
        ),
    }
    manifest = {
        "schema": "chronos.experiment-a-qwen-cell-collection.v1",
        "cell_collection_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "status": "sealed_raw_revalidated",
        "model": batch00.MODEL,
        "reasoning": batch00.REASONING,
        "role": batch00.ROLE,
        "study_id": batch00.STUDY_ID,
        "pilot_collection_manifest_sha256": batch_manifests[0][
            "pilot_collection_manifest_sha256"
        ],
        "deterministic_full_jobs_sha256": manifest_digest(full_jobs),
        "batch_count": len(records),
        "totals": totals,
        "batches": records,
    }
    manifest["cell_collection_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load_manifest(value: dict | None = None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if _manifest_hash(manifest) != manifest.get(
        "cell_collection_manifest_sha256"
    ):
        raise ValueError("Qwen cell collection manifest self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load_manifest(value)
    expected = build_manifest()
    if manifest != expected:
        raise ValueError("Qwen cell collection differs from raw regeneration")
    totals = manifest["totals"]
    if (
        manifest["schema"]
        != "chronos.experiment-a-qwen-cell-collection.v1"
        or manifest["status"] != "sealed_raw_revalidated"
        or manifest["batch_count"] != 5
        or totals["shards"] != 30
        or totals["jobs"] != 690
        or totals["planned_calls"] != 2310
        or totals["observed_invocations"] != 2310
        or totals["complete_calls"] != 2310
        or totals["failed_calls"] != 0
        or totals["unknown_cost_calls"] != 0
        or totals["invalid_json_lines"] != 0
        or totals["events"] != 3690
        or totals["started_attempts"] != 690
        or totals["technical_relaunches"] != 3
        or totals["superseded_no_run"] != 3
    ):
        raise ValueError("Qwen full-cell topology or accounting changed")
    batch00._require_equal(
        totals["known_cost_usd"], CELL_KNOWN_COST_USD, "Qwen cell cost"
    )
    batch00._require_equal(
        totals["pre_cell_known_daily_cost_usd"],
        PRE_CELL_KNOWN_DAILY_COST_USD,
        "Qwen pre-cell known daily cost",
    )
    batch00._require_equal(
        totals["post_cell_known_daily_cost_usd"],
        POST_CELL_KNOWN_DAILY_COST_USD,
        "Qwen post-cell known daily cost",
    )
    return {
        "schema": "chronos.experiment-a-qwen-cell-verification.v1",
        "cell_collection_manifest_sha256": manifest[
            "cell_collection_manifest_sha256"
        ],
        "model": manifest["model"],
        "reasoning": manifest["reasoning"],
        **totals,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    if args.write_manifest:
        manifest = build_manifest()
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(
            f"WROTE {MANIFEST} "
            f"{manifest['cell_collection_manifest_sha256']}"
        )
    checked = verify()
    print(
        "PASS Qwen full cell: {jobs}/690 jobs, {planned_calls}/2310 planned "
        "calls, {observed_invocations}/2310 measured invocations, "
        "{failed_calls} failed calls, ${known_cost_usd:.8f} cell / "
        "${post_cell_known_daily_cost_usd:.8f} known daily total; 30 shards "
        "form an exact deterministic partition".format(**checked)
    )


if __name__ == "__main__":
    main()
