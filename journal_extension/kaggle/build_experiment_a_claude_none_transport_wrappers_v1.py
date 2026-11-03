"""Build hash-checked transport wrappers for oversized Claude task sources."""

from __future__ import annotations

import argparse
import ast
import base64
import copy
import json
from pathlib import Path
import zlib

import verify_experiment_a_claude_none_batch00 as staged_batch
import verify_experiment_a_gemini_batch00 as stage_base
import verify_experiment_a_qwen_batch00_collection as evidence_base


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_claude_none_batch00"
ATTESTATION = RUNS / "transport_wrappers_s00_s01_s03_s06_v1.json"
FROZEN_AT = "2026-09-21T19:45:48.859187+00:00"
SHARDS = (0, 1, 3, 4, 5, 6)


def _wrapper_path(shard: int) -> Path:
    return GENERATED / f"water4_study_claude_none_s{shard:02d}_transport_v1.py"


def build_wrapper(shard: int) -> str:
    if shard not in SHARDS:
        raise ValueError("shard is outside the frozen transport-wrapper set")
    canonical = staged_batch._source(shard).read_bytes()
    encoded = base64.b85encode(zlib.compress(canonical, level=9))
    digest = stage_base._sha256(canonical)
    task = staged_batch._task(shard)
    return f'''# Deterministic transport wrapper; scientific payload is byte-pinned.
import base64 as _transport_base64
import hashlib as _transport_hashlib
import zlib as _transport_zlib

# This unreachable declaration lets the Kaggle CLI identify the task slug
# without changing or executing the canonical scientific payload.
if False:
    @task(name={task!r})
    def _transport_task_marker(llm):
        pass

_TRANSPORT_PAYLOAD_B85 = {encoded!r}
_TRANSPORT_PAYLOAD_SHA256 = {digest!r}
_transport_payload = _transport_zlib.decompress(
    _transport_base64.b85decode(_TRANSPORT_PAYLOAD_B85)
)
if _transport_hashlib.sha256(_transport_payload).hexdigest() != (
    _TRANSPORT_PAYLOAD_SHA256
):
    raise ValueError("Canonical Experiment A payload hash mismatch")
exec(
    compile(
        _transport_payload,
        {f'water4_study_claude_none_s{shard:02d}_v1.py'!r},
        "exec",
    ),
    globals(),
    globals(),
)
'''


def _literal_assignments(source: str, path: Path) -> dict:
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


def verify_wrapper(shard: int) -> dict:
    path = _wrapper_path(shard)
    raw = path.read_bytes()
    source = raw.decode()
    if source != build_wrapper(shard):
        raise ValueError(f"Claude s{shard:02d} transport wrapper changed")
    values = _literal_assignments(source, path)
    canonical = staged_batch._source(shard).read_bytes()
    payload = zlib.decompress(
        base64.b85decode(values["_TRANSPORT_PAYLOAD_B85"])
    )
    if (
        payload != canonical
        or values["_TRANSPORT_PAYLOAD_SHA256"]
        != stage_base._sha256(canonical)
    ):
        raise ValueError(f"Claude s{shard:02d} transport payload changed")
    compile(source, str(path), "exec")
    return {
        "shard_index": shard,
        "task": staged_batch._task(shard),
        "canonical_source": evidence_base._file_record(
            staged_batch._source(shard)
        ),
        "wrapper_source": evidence_base._file_record(path),
        "decompressed_payload_sha256": stage_base._sha256(payload),
        "scientific_changes": [],
        "transport_change": (
            "zlib_level9_base85_wrapper_with_pre_execution_sha256_check"
        ),
    }


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
    wrappers = [verify_wrapper(shard) for shard in SHARDS]
    attestation = {
        "schema": "chronos.experiment-a-transport-wrapper-batch.v1",
        "attestation_sha256": None,
        "frozen_at": FROZEN_AT,
        "reason": (
            "Kaggle CreateBenchmarkTask returned HTTP 499 with an empty body "
            "for the canonical approximately-198-KiB sources"
        ),
        "prelaunch_manifest": evidence_base._file_record(staged_batch.MANIFEST),
        "prelaunch_manifest_sha256": staged["batch_manifest_sha256"],
        "canonical_task_source_status": "frozen_prelaunch",
        "wrapper_count": len(wrappers),
        "wrappers": wrappers,
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
        raise ValueError("Claude transport-wrapper attestation self-hash mismatch")
    return attestation


def verify(value: dict | None = None) -> dict:
    attestation = _load(value)
    expected = build_attestation()
    if attestation != expected:
        raise ValueError("Claude transport-wrapper attestation changed")
    if (
        attestation["schema"]
        != "chronos.experiment-a-transport-wrapper-batch.v1"
        or attestation["wrapper_count"] != 6
        or [item["shard_index"] for item in attestation["wrappers"]]
        != list(SHARDS)
        or any(item["scientific_changes"] for item in attestation["wrappers"])
    ):
        raise ValueError("Claude transport-wrapper contract changed")
    return attestation


def write_wrappers() -> None:
    for shard in SHARDS:
        path = _wrapper_path(shard)
        path.write_text(build_wrapper(shard))
        print(f"WROTE {path} {stage_base._sha256(path.read_bytes())}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        write_wrappers()
        attestation = build_attestation()
        ATTESTATION.write_text(
            json.dumps(attestation, indent=2, sort_keys=True) + "\n"
        )
        print(f"WROTE {ATTESTATION} {attestation['attestation_sha256']}")
    checked = verify()
    print(
        "PASS Claude transport wrappers: "
        f"{checked['wrapper_count']} wrappers, byte-exact decompression, "
        "zero scientific changes"
    )


if __name__ == "__main__":
    main()
