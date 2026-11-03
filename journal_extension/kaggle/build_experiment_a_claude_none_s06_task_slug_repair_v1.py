"""Build and attest the Claude-none shard-06 no-run task-slug repair."""

from __future__ import annotations

import argparse
import ast
import base64
import copy
import json
from pathlib import Path
import zlib

import build_experiment_a_claude_none_transport_wrappers_v1 as transport_batch
import verify_experiment_a_claude_none_batch00 as staged_batch
import verify_experiment_a_gemini_batch00 as stage_base
import verify_experiment_a_qwen_batch00_collection as evidence_base


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_claude_none_batch00"
ORIGINAL = GENERATED / "water4_study_claude_none_s06_v1.py"
REPAIR = GENERATED / "water4_study_claude_none_s06_repair_v1.py"
WRAPPER = GENERATED / "water4_study_claude_none_s06_repair_transport_v1.py"
ATTESTATION = RUNS / "s06_version1_no_run_attestation_v1.json"

ORIGINAL_TASK = "chronos-r2-water4-study-claude-none-s06-v1"
REPAIR_TASK = "chronos-r2-water4-study-claude-none-s06-repair-v1"
ORIGINAL_SHA256 = (
    "151af7b6b622cc27ce9dbd63756425eeb5d4c2c479c37899a7b1c67047cc05a6"
)
REPAIR_SHA256 = (
    "971f0fc3901f169e49a9016a5cfeecbc3d179b2eecec3b8a94671497ee953750"
)
CAPTURED_AT = "2026-09-21T19:58:11.684648+00:00"
TASK_VERSION_BEFORE_REPAIR = {
    "createTime": "2026-09-21T19:55:42.916Z",
    "creationErrorMessage": None,
    "creationState": "BENCHMARK_TASK_VERSION_CREATION_STATE_UNSPECIFIED",
    "error": None,
    "isBackingNotebookPublished": None,
    "isPublic": False,
    "options": None,
    "runs": [],
    "slug": {
        "ownerSlug": "masihmaafi",
        "taskSlug": ORIGINAL_TASK,
        "versionNumber": 1,
    },
    "source": "BENCHMARK_TASK_VERSION_SOURCE_UNSPECIFIED",
    "sourceKernelId": None,
    "url": f"/benchmarks/tasks/masihmaafi/{ORIGINAL_TASK}/1",
}


def build_repair() -> bytes:
    original = ORIGINAL.read_bytes()
    if stage_base._sha256(original) != ORIGINAL_SHA256:
        raise ValueError("canonical Claude shard-06 source hash changed")
    old = f"@kbench.task(name={ORIGINAL_TASK!r})".encode()
    new = f"@kbench.task(name={REPAIR_TASK!r})".encode()
    if original.count(old) != 1 or new in original:
        raise ValueError("Claude shard-06 task decorator is not unique")
    repaired = original.replace(old, new)
    if repaired.replace(new, old) != original:
        raise ValueError("Claude shard-06 repair is not exactly reversible")
    if stage_base._sha256(repaired) != REPAIR_SHA256:
        raise ValueError("Claude shard-06 repair source hash changed")
    return repaired


def build_wrapper() -> str:
    repaired = build_repair()
    encoded = base64.b85encode(zlib.compress(repaired, level=9))
    return f'''# Deterministic transport wrapper for the shard-06 task-slug repair.
import base64 as _transport_base64
import hashlib as _transport_hashlib
import zlib as _transport_zlib

if False:
    @task(name={REPAIR_TASK!r})
    def _transport_task_marker(llm):
        pass

_TRANSPORT_PAYLOAD_B85 = {encoded!r}
_TRANSPORT_PAYLOAD_SHA256 = {REPAIR_SHA256!r}
_transport_payload = _transport_zlib.decompress(
    _transport_base64.b85decode(_TRANSPORT_PAYLOAD_B85)
)
if _transport_hashlib.sha256(_transport_payload).hexdigest() != (
    _TRANSPORT_PAYLOAD_SHA256
):
    raise ValueError("Repaired Experiment A payload hash mismatch")
exec(
    compile(_transport_payload, {REPAIR.name!r}, "exec"),
    globals(),
    globals(),
)
'''


def _literal_assignments(source: str) -> dict:
    values = {}
    for node in ast.parse(source, str(WRAPPER)).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    values[target.id] = ast.literal_eval(node.value)
                except (TypeError, ValueError):
                    pass
    return values


def verify_sources() -> tuple[bytes, bytes]:
    repaired = build_repair()
    if REPAIR.read_bytes() != repaired:
        raise ValueError("written Claude shard-06 repair source changed")
    wrapper = WRAPPER.read_bytes()
    expected_wrapper = build_wrapper().encode()
    if wrapper != expected_wrapper:
        raise ValueError("written Claude shard-06 repair wrapper changed")
    values = _literal_assignments(wrapper.decode())
    decoded = zlib.decompress(
        base64.b85decode(values["_TRANSPORT_PAYLOAD_B85"])
    )
    if decoded != repaired:
        raise ValueError("Claude shard-06 wrapper payload changed")
    compile(wrapper.decode(), str(WRAPPER), "exec")
    return repaired, wrapper


def _attestation_hash(value: dict) -> str:
    return stage_base._canonical_hash(
        {
            key: item
            for key, item in value.items()
            if key != "attestation_sha256"
        }
    )


def build_attestation() -> dict:
    staged = staged_batch.verify()
    transport = transport_batch.verify()
    repaired, wrapper = verify_sources()
    repair = {
        "shard_index": 6,
        "original_task": ORIGINAL_TASK,
        "task_version_before_repair": TASK_VERSION_BEFORE_REPAIR,
        "model_run_observed": False,
        "same_slug_repush_attempt": {
            "error": (
                "Task 'masihmaafi/"
                f"{ORIGINAL_TASK}' exists but has no source kernel."
            ),
            "run_created": False,
        },
        "repair_task": REPAIR_TASK,
        "repair_source": {
            **evidence_base._file_record(REPAIR),
            "derived_from_sha256": ORIGINAL_SHA256,
            "transformation": (
                f"replace the sole kbench task decorator slug {ORIGINAL_TASK} "
                f"with {REPAIR_TASK}; reverse substitution reproduces "
                "derived_from_sha256"
            ),
        },
        "transport_wrapper": {
            **evidence_base._file_record(WRAPPER),
            "decompressed_payload_sha256": stage_base._sha256(repaired),
        },
        "scientific_changes": [],
        "unaccounted_quota_usd": 0.0,
    }
    attestation = {
        "schema": "chronos.kaggle-task-version-repair-batch-attestation.v1",
        "attestation_sha256": None,
        "captured_at_utc": CAPTURED_AT,
        "conclusion": (
            "original_version_created_without_source_kernel_or_run; frozen "
            "contract relaunched with only task slug rewritten"
        ),
        "prelaunch_manifest_sha256": staged["batch_manifest_sha256"],
        "transport_attestation_sha256": transport["attestation_sha256"],
        "repairs": [repair],
    }
    attestation["attestation_sha256"] = _attestation_hash(attestation)
    return attestation


def _load(value: dict | None = None) -> dict:
    attestation = (
        json.loads(ATTESTATION.read_text())
        if value is None
        else copy.deepcopy(value)
    )
    if attestation.get("attestation_sha256") != _attestation_hash(attestation):
        raise ValueError("Claude shard-06 repair attestation self-hash mismatch")
    return attestation


def verify(value: dict | None = None) -> dict:
    attestation = _load(value)
    if attestation != build_attestation():
        raise ValueError("Claude shard-06 repair attestation changed")
    repair = attestation["repairs"][0]
    if (
        repair["task_version_before_repair"]["runs"] != []
        or repair["model_run_observed"] is not False
        or repair["scientific_changes"] != []
        or repair["unaccounted_quota_usd"] != 0.0
        or stage_base._sha256(build_repair()) != REPAIR_SHA256
    ):
        raise ValueError("Claude shard-06 repair contract changed")
    return attestation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        repair = build_repair()
        wrapper = build_wrapper().encode()
        for path, raw in ((REPAIR, repair), (WRAPPER, wrapper)):
            if path.exists() and path.read_bytes() != raw:
                raise ValueError(f"refusing to overwrite different source: {path}")
            path.write_bytes(raw)
            print(f"WROTE {path} {stage_base._sha256(raw)}")
        attestation = build_attestation()
        ATTESTATION.write_text(
            json.dumps(attestation, indent=2, sort_keys=True) + "\n"
        )
        print(f"WROTE {ATTESTATION} {attestation['attestation_sha256']}")
    checked = verify()
    print(
        "PASS Claude s06 repair: one reversible task-slug change, no run on "
        f"the original shell, attestation {checked['attestation_sha256']}"
    )


if __name__ == "__main__":
    main()
